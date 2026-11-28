"""Theatres, sessions and cases (CEDA HS03, WF05 step 2; UAT WF05).

A case books time in an open session; a session is never overbooked, and an
unavailable theatre takes no case. The safety checklist comes before the
operation, or an override with a reason. Cancelling gives the time back and
sends one review task; recovery hands over to a named recipient.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import Encounter, OutboxEvent, Task, TheatreCase, TheatreSession
from tests.conftest import Api
from tests.e2e.test_api03_vertical_slice import admit, register
from tests.e2e.test_care_plans import plan
from tests.e2e.test_scheduling import facility

TOMORROW = datetime.now(UTC).replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(days=1)


def if_match(version: int) -> dict[str, str]:
    return {"If-Match": f'"{version}"'}


def code(r: Any) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


def theatre(api: Api, theatre_code: str = "T1", facility_id: str | None = None) -> dict[str, Any]:
    body = {
        "facility_id": facility_id or str(api.tenant.facility_id),
        "code": theatre_code,
        "name": f"Theatre {theatre_code}",
    }
    made = api.post("admin", "/v1/theatres", body)
    assert made.status_code == 201, made.text
    return made.json()


def session_in(api: Api, t: dict[str, Any], start: datetime = TOMORROW, hours: int = 2) -> Any:
    return api.post(
        "admin",
        f"/v1/theatres/{t['id']}/sessions",
        {"starts_at": start.isoformat(), "ends_at": (start + timedelta(hours=hours)).isoformat()},
    )


def book(
    api: Api, slot: str, enc: dict[str, Any], minutes: int, who: str = "scheduler", **x: Any
) -> Any:
    return api.post(
        who,
        "/v1/theatre-cases",
        {
            "session_id": slot,
            "encounter_id": enc["id"],
            "surgeon_id": str(api.tenant.practitioners["clinician"]),
            "procedure": "Laparoscopic cholecystectomy",
            "procedure_code": "J18.3",
            "laterality": "not_applicable",
            "estimated_minutes": minutes,
            **x,
        },
    )


def act(api: Api, who: str, case: str, verb: str, version: int, body: dict[str, Any]) -> Any:
    return api.post(who, f"/v1/theatre-cases/{case}/{verb}", body, **if_match(version))


def test_theatres_and_sessions_are_set_up_by_administrators(
    api: Api, factory: sessionmaker[Session]
) -> None:
    t = theatre(api)
    body = {"facility_id": str(api.tenant.facility_id), "code": "T1", "name": "Again"}
    assert code(api.post("admin", "/v1/theatres", body)) == (409, "theatre_code_exists")
    missing = {**body, "code": "T9", "facility_id": str(uuid.uuid4())}
    assert api.post("admin", "/v1/theatres", missing).status_code == 404
    assert code(api.post("nurse", "/v1/theatres", {**body, "code": "T2"})) == (
        403,
        "missing_capability",
    )
    made = session_in(api, t)
    assert made.status_code == 201, made.text
    assert (made.json()["capacity_minutes"], made.json()["booked_minutes"]) == (120, 0)
    # Sessions in one theatre do not overlap, and end after they start.
    assert code(session_in(api, t, TOMORROW + timedelta(hours=1))) == (409, "session_overlap")
    assert code(session_in(api, t, TOMORROW + timedelta(hours=4), hours=0)) == (
        422,
        "bad_session_times",
    )
    assert session_in(api, t, TOMORROW + timedelta(hours=2)).status_code == 201
    nowhere = {
        "starts_at": TOMORROW.isoformat(),
        "ends_at": (TOMORROW + timedelta(hours=1)).isoformat(),
    }
    assert api.post("admin", f"/v1/theatres/{uuid.uuid4()}/sessions", nowhere).status_code == 404
    assert [x["code"] for x in api.get("scheduler", "/v1/theatres").json()] == ["T1"]
    listed = api.get("nurse", f"/v1/theatre-sessions?theatre_id={t['id']}").json()
    assert [s["theatre_code"] for s in listed] == ["T1", "T1"]
    assert api.get("registrar", f"/v1/theatre-sessions?theatre_id={uuid.uuid4()}").json() == []
    assert len(api.get("registrar", "/v1/theatre-sessions").json()) == 2
    assert api.get("clerk", "/v1/theatre-sessions").status_code == 403
    # A session that has ended no longer shows.
    with factory() as s, s.begin():
        s.execute(
            update(TheatreSession)
            .where(TheatreSession.id == uuid.UUID(made.json()["id"]))
            .values(
                starts_at=datetime.now(UTC) - timedelta(hours=3),
                ends_at=datetime.now(UTC) - timedelta(hours=1),
            )
        )
    assert len(api.get("registrar", "/v1/theatre-sessions").json()) == 1


def test_a_session_is_never_overbooked_and_an_unavailable_theatre_takes_no_case(
    api: Api, factory: sessionmaker[Session]
) -> None:
    t = theatre(api)
    slot = session_in(api, t).json()["id"]
    pid = register(api)
    enc = admit(api, pid)
    first = book(api, slot, enc, 90)
    assert first.status_code == 201, first.text
    assert first.json()["status"] == "scheduled"
    assert code(book(api, slot, enc, 60)) == (409, "session_full")
    assert book(api, slot, enc, 30, who="clinician").status_code == 201
    listed = api.get("scheduler", "/v1/theatre-sessions").json()[0]
    assert (listed["booked_minutes"], len(listed["cases"])) == (120, 2)
    # A booked session cannot be closed; an empty one can, and then takes no case.
    assert code(
        api.post(
            "admin", f"/v1/theatre-sessions/{slot}/status", {"status": "unavailable"}, **if_match(3)
        )
    ) == (409, "session_has_cases")
    other = session_in(api, t, TOMORROW + timedelta(hours=3)).json()
    closed = api.post(
        "admin",
        f"/v1/theatre-sessions/{other['id']}/status",
        {"status": "unavailable", "reason": "Laminar flow fault"},
        **if_match(1),
    )
    assert closed.status_code == 200, closed.text
    assert code(book(api, other["id"], enc, 30)) == (409, "theatre_unavailable")  # UAT WF05
    api.post(
        "admin", f"/v1/theatre-sessions/{other['id']}/status", {"status": "open"}, **if_match(2)
    )
    shut = api.post("admin", f"/v1/theatres/{t['id']}/status", {"active": False}, **if_match(1))
    assert shut.json()["active"] is False
    assert code(book(api, other["id"], enc, 30)) == (409, "theatre_unavailable")
    api.post("admin", f"/v1/theatres/{t['id']}/status", {"active": True}, **if_match(2))

    # Bookings that do not fit the patient are refused.
    other_pid = register(api, "71111111111")
    admit(api, other_pid, visit="V-S")
    stranger = plan(api, other_pid).json()
    assert code(book(api, other["id"], enc, 30, care_plan_id=stranger["id"])) == (
        422,
        "plan_for_another_patient",
    )
    assert book(api, other["id"], enc, 30, surgeon_id=str(uuid.uuid4())).status_code == 404
    assert book(api, str(uuid.uuid4()), enc, 30).status_code == 404
    elsewhere = theatre(api, "T9", facility(factory, api, "teaching_hospital"))
    far = session_in(api, elsewhere).json()["id"]
    assert code(book(api, far, enc, 30)) == (422, "theatre_in_another_facility")
    with factory() as s, s.begin():
        s.execute(
            update(TheatreSession)
            .where(TheatreSession.id == uuid.UUID(other["id"]))
            .values(ends_at=datetime.now(UTC) - timedelta(minutes=1))
        )
    assert code(book(api, other["id"], enc, 30)) == (422, "session_ended")
    with factory() as s, s.begin():
        s.execute(
            update(Encounter).where(Encounter.id == uuid.UUID(enc["id"])).values(state="finished")
        )
    assert code(book(api, slot, enc, 5)) == (422, "encounter_not_open")
    assert code(book(api, slot, enc, 30, who="nurse")) == (404, "not_found")


def test_the_checklist_comes_first_and_recovery_hands_over_to_a_named_recipient(
    api: Api, factory: sessionmaker[Session]
) -> None:
    t = theatre(api)
    slot = session_in(api, t, hours=4).json()["id"]
    pid = register(api)
    enc = admit(api, pid)
    case = book(api, slot, enc, 90).json()["id"]

    assert code(act(api, "clinician", case, "start", 1, {})) == (422, "checklist_incomplete")
    assert code(act(api, "nurse", case, "checklist", 1, {"step": "sign_out"})) == (
        422,
        "step_out_of_order",
    )
    assert act(api, "nurse", case, "checklist", 1, {"step": "sign_in"}).status_code == 200
    assert code(act(api, "nurse", case, "checklist", 2, {"step": "sign_in"})) == (
        422,
        "step_recorded",
    )
    timed = act(api, "clinician", case, "checklist", 2, {"step": "time_out"})
    assert [e["step"] for e in timed.json()["checklist"]] == ["sign_in", "time_out"]
    assert act(api, "nurse", case, "start", 3, {}).status_code == 404  # not hers to start
    started = act(api, "clinician", case, "start", 3, {})
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "in_theatre" and started.json()["override_reason"] is None
    assert code(act(api, "clinician", case, "cancel", 4, {"reason": "x"})) == (
        422,
        "invalid_transition",
    )
    note = {"procedure_note": "Uncomplicated. Specimen to histology."}
    assert code(act(api, "clinician", case, "complete", 4, note)) == (422, "checklist_incomplete")
    act(api, "nurse", case, "checklist", 4, {"step": "sign_out"})
    done = act(api, "clinician", case, "complete", 5, note)
    assert done.json()["status"] == "completed", done.text

    me = str(api.tenant.practitioners["clinician"])
    assert code(act(api, "clinician", case, "handover", 6, {"recipient_id": me})) == (
        422,
        "handover_to_self",
    )
    nurse = str(api.tenant.practitioners["nurse"])
    over = act(api, "clinician", case, "handover", 6, {"recipient_id": nurse, "note": "Stable"})
    assert over.status_code == 200, over.text
    body = over.json()
    assert (body["status"], body["handover_recipient_id"]) == ("handed_over", nurse)
    [task_id] = body["tasks"]
    with factory() as s:
        task = s.get(Task, (api.tenant.tenant_id, uuid.UUID(task_id)))
        assert task is not None
        assert (task.task_type, task.priority) == ("handover", "urgent")
        kinds = set(
            s.scalars(
                select(OutboxEvent.event_type).where(OutboxEvent.aggregate_id == uuid.UUID(case))
            )
        )
    assert {"theatre_case.booked", "theatre_case.handed_over"} <= kinds

    # An authorised override, with its reason, stands in for missing steps.
    other = book(api, slot, enc, 60).json()["id"]
    why = "Emergency: no time for the time-out"
    went = act(api, "clinician", other, "start", 1, {"override_reason": why})
    assert went.json()["override_reason"] == why
    finished = act(
        api, "clinician", other, "complete", 2, {**note, "override_reason": "Count done verbally"}
    )
    assert finished.json()["override_reason"] == f"{why}; Count done verbally"


def test_a_cancelled_operation_releases_its_time_and_sends_one_review_task(
    api: Api, factory: sessionmaker[Session]
) -> None:
    """CEDA HS03 acceptance; the ambulatory surgery acceptance (one follow-up task)."""
    t = theatre(api)
    slot = session_in(api, t).json()["id"]
    pid = register(api)
    enc = admit(api, pid)
    care_plan = plan(api, pid).json()
    planned = book(api, slot, enc, 120, care_plan_id=care_plan["id"]).json()
    assert code(book(api, slot, enc, 30)) == (409, "session_full")
    cancelled = act(api, "scheduler", planned["id"], "cancel", 1, {"reason": "Patient unwell"})
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    [task_id] = cancelled.json()["tasks"]
    listed = api.get("scheduler", "/v1/theatre-sessions").json()[0]
    assert (listed["booked_minutes"], listed["cases"]) == (0, [])
    assert book(api, slot, enc, 120).status_code == 201  # the time is free again
    with factory() as s:
        task = s.get(Task, (api.tenant.tenant_id, uuid.UUID(task_id)))
        assert task is not None
        assert (task.task_type, task.assignee_id) == (
            "plan_review",
            uuid.UUID(care_plan["owner_id"]),
        )

    # Without a plan, the surgeon gets the review.
    slot2 = session_in(api, t, TOMORROW + timedelta(hours=3)).json()["id"]
    lone = book(api, slot2, enc, 30, surgeon_id=str(api.tenant.practitioners["clinician2"]))
    gone = act(api, "clinician", lone.json()["id"], "cancel", 1, {"reason": "List overran"})
    with factory() as s:
        task = s.get(Task, (api.tenant.tenant_id, uuid.UUID(gone.json()["tasks"][0])))
        assert task is not None
        assert task.assignee_id == api.tenant.practitioners["clinician2"]


def test_a_case_is_read_by_the_care_team_and_withheld_like_the_chart(
    api: Api, factory: sessionmaker[Session]
) -> None:
    t = theatre(api)
    slot = session_in(api, t).json()["id"]
    pid = register(api)
    enc = admit(api, pid)
    case = book(api, slot, enc, 60).json()["id"]
    read = api.get("clinician", f"/v1/theatre-cases/{case}")
    assert read.status_code == 200 and read.json()["theatre_id"] == t["id"]
    assert api.get("clinician2", f"/v1/theatre-cases/{case}").status_code == 404
    assert api.get("clinician", f"/v1/theatre-cases/{uuid.uuid4()}").status_code == 404
    with factory() as s, s.begin():
        s.execute(
            update(TheatreCase)
            .where(TheatreCase.id == uuid.UUID(case))
            .values(sensitivity="mental_health")
        )
    assert api.get("clinician", f"/v1/theatre-cases/{case}").status_code == 404
