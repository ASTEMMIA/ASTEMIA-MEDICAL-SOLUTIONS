"""Daybook tasks (CEDA UG03).

UG03 acceptance: an overdue recall remains visible after staff reassignment;
completion records actor and time and prevents a duplicate reminder; a
supervisor reassigns an overdue task while a reminder is retried, and one
reminder and the complete ownership history remain."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import OutboxEvent, Task, TaskNotification
from astemia.workers.reminders import send_reminders
from tests.conftest import Api
from tests.db_integration.test_runtime import run_cli
from tests.e2e.test_api03_vertical_slice import admit, register
from tests.e2e.test_documents import file, receive

NOW = datetime.now(UTC)


def if_match(version: int) -> dict[str, str]:
    return {"If-Match": f'"{version}"'}


def code(r: Any) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


def task(api: Api, who: str = "clinician", **extra: Any) -> dict[str, Any]:
    body = {
        "subject": "Recall for repeat potassium",
        "task_type": "recall",
        "due_at": (NOW - timedelta(hours=1)).isoformat(),
        "assignee_id": str(api.tenant.practitioners["clinician"]),
        **extra,
    }
    r = api.post(who, "/v1/tasks", body)
    assert r.status_code == 201, r.text
    return r.json()


def mine(api: Api, who: str) -> list[str]:
    return [t["id"] for t in api.get(who, "/v1/tasks").json()]


def notifications(factory: sessionmaker[Session], task_id: str) -> list[int]:
    with factory() as s:
        return sorted(
            s.scalars(
                select(TaskNotification.step).where(TaskNotification.task_id == uuid.UUID(task_id))
            ).all()
        )


def test_a_queue_task_is_claimed_and_completed(api: Api) -> None:
    pid = register(api)
    t = task(
        api,
        patient_id=pid,
        assignee_id=None,
        queue="nurse",
        due_at=(NOW + timedelta(days=1)).isoformat(),
    )
    assert (t["status"], t["queue"], t["overdue"]) == ("open", "nurse", False)
    assert t["id"] in mine(api, "nurse") and t["id"] not in mine(api, "clinician2")
    path = f"/v1/tasks/{t['id']}"
    assert code(api.post("nurse", f"{path}/acknowledge", {})) == (428, "precondition_required")
    assert api.post("clinician2", f"{path}/acknowledge", {}, **if_match(1)).status_code == 404
    claimed = api.post("nurse", f"{path}/acknowledge", {}, **if_match(1))
    assert claimed.status_code == 200, claimed.text
    out = claimed.json()
    assert (out["status"], out["assignee_id"]) == (
        "acknowledged",
        str(api.tenant.practitioners["nurse"]),
    )
    assert [h["reason"] for h in out["history"]] == ["created", "claimed from queue"]
    done = api.post("nurse", f"{path}/complete", {"note": "Bloods taken"}, **if_match(2))
    assert done.status_code == 200, done.text
    assert done.json()["completed_by_id"] == str(api.tenant.practitioners["nurse"])
    assert done.json()["completed_at"] is not None
    assert code(api.post("nurse", f"{path}/complete", {}, **if_match(3))) == (
        422,
        "invalid_transition",
    )
    assert t["id"] not in mine(api, "nurse")  # done: off the worklist
    both = {
        "subject": "x" * 5,
        "due_at": NOW.isoformat(),
        "assignee_id": str(api.tenant.practitioners["nurse"]),
        "queue": "nurse",
    }
    assert code(api.post("clinician", "/v1/tasks", both)) == (422, "assignee_or_queue")
    assert api.post("psychiatrist", "/v1/tasks", both).status_code == 422  # clinicians assign
    assert api.post("advocate", "/v1/tasks", both).status_code == 403


def test_an_overdue_recall_stays_visible_after_reassignment_with_one_reminder(
    api: Api, factory: sessionmaker[Session]
) -> None:
    t = task(api)
    assert t["overdue"] is True
    assert api.get("clinician", "/v1/tasks?view=all").status_code == 403
    assert t["id"] in [x["id"] for x in api.get("supervisor", "/v1/tasks?view=all").json()]

    # The first reminder goes to the current owner; a retry sends nothing more.
    send_reminders(factory, NOW)
    send_reminders(factory, NOW)
    assert notifications(factory, t["id"]) == [1]

    # A supervisor reassigns the overdue recall while the reminder is retried.
    path = f"/v1/tasks/{t['id']}"
    moved = api.post(
        "supervisor",
        f"{path}/reassign",
        {"assignee_id": str(api.tenant.practitioners["clinician2"]), "reason": "Dr One on leave"},
        **if_match(1),
    )
    assert moved.status_code == 200, moved.text
    out = moved.json()
    assert out["due_at"] == t["due_at"] and out["overdue"] is True  # the deadline holds
    assert [h["reason"] for h in out["history"]] == ["created", "Dr One on leave"]
    assert t["id"] in mine(api, "clinician2") and t["id"] not in mine(api, "clinician")
    send_reminders(factory, NOW)
    assert notifications(factory, t["id"]) == [1]  # still one reminder for this step

    # A day later the next step escalates to the supervisors.
    send_reminders(factory, NOW + timedelta(hours=24))
    assert notifications(factory, t["id"]) == [1, 2]
    with factory() as s:
        kinds = s.scalars(
            select(OutboxEvent.event_type).where(
                OutboxEvent.aggregate_id == uuid.UUID(t["id"]),
                OutboxEvent.event_type.in_(["task.reminder", "task.escalated"]),
            )
        ).all()
        step = s.get(Task, (api.tenant.tenant_id, uuid.UUID(t["id"])))
    assert sorted(kinds) == ["task.escalated", "task.reminder"]
    assert step is not None and step.escalation_step == 2

    # Completion stops the reminders.
    api.post("clinician2", f"{path}/complete", {}, **if_match(2))
    send_reminders(factory, NOW + timedelta(hours=48))
    assert notifications(factory, t["id"]) == [1, 2]
    assert code(
        api.post(
            "supervisor",
            f"{path}/reassign",
            {"queue": "nurse", "reason": "too late"},
            **if_match(3),
        )
    ) == (422, "task_closed")
    assert code(
        api.post("supervisor", f"{path}/reassign", {"reason": "nobody"}, **if_match(3))
    ) == (422, "task_closed")
    assert run_cli(["reminders"], factory).strip().isdigit()


def test_cancel_records_who_and_why(api: Api) -> None:
    t = task(api, assignee_id=str(api.tenant.practitioners["nurse"]))
    gone = api.post(
        "nurse", f"/v1/tasks/{t['id']}/cancel", {"reason": "Duplicate recall"}, **if_match(1)
    )
    assert gone.status_code == 200, gone.text
    assert (gone.json()["status"], gone.json()["outcome_note"]) == ("cancelled", "Duplicate recall")
    assert (
        api.post(
            "clinician2",
            "/v1/tasks",
            {
                "subject": "Unknown owner",
                "due_at": NOW.isoformat(),
                "assignee_id": str(uuid.uuid4()),
            },
        ).status_code
        == 404
    )


def test_a_filed_document_gives_its_reviewer_one_task(
    api: Api, factory: sessionmaker[Session]
) -> None:
    pid = register(api)
    other = register(api, "44444444444")
    doc = receive(api).json()
    filed = file(api, doc, pid)
    assert filed.status_code == 200, filed.text
    [review_task] = [
        t for t in api.get("clinician", "/v1/tasks").json() if t["origin_id"] == doc["id"]
    ]
    assert (review_task["task_type"], review_task["patient_id"]) == ("document_review", pid)

    # Re-filed before review: the first task is cancelled and a new one opened.
    refiled = api.post(
        "clerk",
        f"/v1/documents/{doc['id']}/reindex",
        {"patient_id": other, "document_type": "letter", "reason": "Wrong patient"},
        **if_match(2),
    )
    assert refiled.status_code == 200, refiled.text
    with factory() as s:
        rows = s.execute(
            select(Task.status, Task.patient_id)
            .where(Task.origin_id == uuid.UUID(doc["id"]))
            .order_by(Task.recorded_at)
        ).all()
    assert [(st, str(p)) for st, p in rows] == [("cancelled", pid), ("open", other)]

    # Reviewing the document completes its task.
    admit(api, other, visit="V-DOC")
    done = api.post(
        "clinician", f"/v1/documents/{doc['id']}/review", {"note": "Seen"}, **if_match(3)
    )
    assert done.status_code == 200, done.text
    with factory() as s:
        statuses = s.scalars(
            select(Task.status)
            .where(Task.origin_id == uuid.UUID(doc["id"]))
            .order_by(Task.recorded_at)
        ).all()
        active = s.scalar(
            select(func.count())
            .select_from(Task)
            .where(
                Task.origin_id == uuid.UUID(doc["id"]), Task.status.in_(["open", "acknowledged"])
            )
        )
    assert statuses == ["cancelled", "completed"] and active == 0
