"""Discharge (CEDA HS05, WF06 step 3, ST08).

HS05 acceptance: an unreported discharge investigation remains assigned to an
accountable reviewer; a missing required owner blocks completion or enters a
supervised exception with reason and review task. ST08: a misdirected or
duplicate completion cannot create a second discharge."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import DischargeSummary, Encounter, OutboxEvent, Task
from tests.conftest import Api
from tests.e2e.test_api03_vertical_slice import admit, order, register, release

NOW = datetime.now(UTC)
TOMORROW = (NOW + timedelta(days=1)).isoformat()


def if_match(version: int) -> dict[str, str]:
    return {"If-Match": f'"{version}"'}


def code(r: Any) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


def draft(api: Api, encounter_id: str, who: str = "clinician", **headers: str) -> Any:
    return api.post(
        who,
        f"/v1/encounters/{encounter_id}/discharge-summary",
        {
            "disposition": "home",
            "summary": "Admitted with chest pain; NSTEMI excluded. Potassium corrected.",
            "follow_up": "Medical doctor review in 2 weeks",
        },
        **headers,
    )


def discharge(api: Api, encounter_id: str, version: int, **body: Any) -> Any:
    return api.post(
        "clinician",
        f"/v1/encounters/{encounter_id}/discharge",
        {"discharged_at": NOW.isoformat(), **body},
        **if_match(version),
    )


def test_discharge_leaves_every_outstanding_item_with_an_owner(
    api: Api, factory: sessionmaker[Session]
) -> None:
    pid = register(api)
    enc = admit(api, pid)
    waiting = order(api, pid, enc["id"])  # no result yet
    resulted = order(api, pid, enc["id"])
    release(api, resulted["id"])  # resulted, not yet acknowledged
    assert code(discharge(api, enc["id"], 1)) == (422, "summary_required")

    first = draft(api, enc["id"])
    assert first.status_code == 201, first.text
    assert first.json()["status"] == "draft"
    assert code(draft(api, enc["id"])) == (428, "precondition_required")
    again = draft(api, enc["id"], **if_match(1))
    assert (again.status_code, again.json()["version"]) == (200, 2)
    assert draft(api, enc["id"], who="clinician2").status_code == 404

    medication = {
        "kind": "medication",
        "description": "Supply discharge medicines",
        "owner_id": str(api.tenant.practitioners["clinician2"]),
        "due_at": TOMORROW,
    }
    follow_up = {
        "kind": "follow_up",
        "description": "Book clinic review",
        "queue": "scheduler",
        "due_at": TOMORROW,
    }
    orphan = {"kind": "referral", "description": "Community nursing referral", "due_at": TOMORROW}
    # A missing owner blocks the discharge, and nothing is changed.
    assert code(discharge(api, enc["id"], 1, outstanding=[medication, orphan])) == (
        422,
        "owner_required",
    )
    both = {**medication, "queue": "nurse"}
    assert code(discharge(api, enc["id"], 1, outstanding=[both])) == (422, "assignee_or_queue")
    with factory() as s:
        still = s.get(Encounter, (api.tenant.tenant_id, uuid.UUID(enc["id"])))
    assert still is not None and still.state == "in_progress"

    # ...unless a supervised exception is recorded with its reason.
    supervised = {**orphan, "exception_reason": "No district nurse covers the patient's area"}
    done = discharge(api, enc["id"], 1, outstanding=[medication, follow_up, supervised])
    assert done.status_code == 200, done.text
    out = done.json()
    assert (out["status"], out["signed_by_id"]) == (
        "signed",
        str(api.tenant.practitioners["clinician"]),
    )
    assert len(out["tasks"]) == 5  # pending order, open review, and three listed items

    with factory() as s:
        tasks = s.execute(
            select(Task.task_type, Task.assignee_id, Task.queue, Task.priority, Task.subject).where(
                Task.origin_id == uuid.UUID(out["id"])
            )
        ).all()
    clinician = api.tenant.practitioners["clinician"]
    results = [t for t in tasks if t.task_type == "result_follow_up"]
    assert len(results) == 2 and all(
        t.assignee_id == clinician and t.priority == "urgent" for t in results
    )  # the unreported investigation stays with its accountable reviewer
    listed = {
        (t.assignee_id, t.queue, t.subject) for t in tasks if t.task_type != "result_follow_up"
    }
    assert listed == {
        (api.tenant.practitioners["clinician2"], None, "Supply discharge medicines"),
        (None, "scheduler", "Book clinic review"),
        (None, "team_supervisor", "No owner: Community nursing referral"),
    }
    assert any(
        t["subject"].startswith("No owner") for t in api.get("supervisor", "/v1/tasks").json()
    )
    assert waiting["result_owner_id"] == str(clinician)

    chart = api.get("clinician", f"/v1/patients/{pid}/chart").json()
    [visit] = chart["encounters"]
    assert (visit["state"], visit["disposition"]) == ("finished", "home")
    assert visit["period_end"] is not None
    assert [d["id"] for d in chart["discharges"]] == [out["id"]]

    # A second or misdirected completion cannot discharge again.
    assert code(discharge(api, enc["id"], 2)) == (409, "already_discharged")
    assert code(draft(api, enc["id"], **if_match(2))) == (409, "already_discharged")
    with factory() as s:
        events = s.scalars(
            select(OutboxEvent.payload).where(
                OutboxEvent.tenant_id == api.tenant.tenant_id,
                OutboxEvent.event_type == "encounter.discharged",
            )
        ).all()
    assert len(events) == 1 and "summary" not in events[0]


def test_discharge_rules(api: Api, factory: sessionmaker[Session]) -> None:
    pid = register(api)
    enc = admit(api, pid)
    assert draft(api, enc["id"], who="nurse").status_code == 404  # not in the nurse's care
    draft(api, enc["id"])
    future = (NOW + timedelta(hours=1)).isoformat()
    assert code(discharge(api, enc["id"], 1, discharged_at=future)) == (422, "bad_discharge_time")
    before = (NOW - timedelta(days=30)).isoformat()
    assert code(discharge(api, enc["id"], 1, discharged_at=before)) == (422, "bad_discharge_time")
    assert code(discharge(api, enc["id"], 9)) == (409, "stale_version")
    assert (
        api.post(
            "nurse",
            f"/v1/encounters/{enc['id']}/discharge",
            {"discharged_at": NOW.isoformat()},
            **if_match(1),
        ).status_code
        == 404
    )  # nurses do not sign off a discharge
    with factory() as s, s.begin():
        s.execute(
            update(Encounter).where(Encounter.id == uuid.UUID(enc["id"])).values(state="cancelled")
        )
    assert code(discharge(api, enc["id"], 1)) == (422, "invalid_transition")
    assert discharge(api, str(uuid.uuid4()), 1).status_code == 404


def test_the_care_team_reads_the_summary_back_draft_or_signed(
    api: Api, factory: sessionmaker[Session]
) -> None:
    pid = register(api)
    enc = admit(api, pid)
    path = f"/v1/encounters/{enc['id']}/discharge-summary"
    assert code(api.get("clinician", path)) == (404, "not_found")  # nothing drafted yet
    draft(api, enc["id"])
    got = api.get("clinician", path)
    assert got.status_code == 200, got.text
    assert (got.json()["status"], got.json()["version"]) == ("draft", 1)  # to edit, If-Match 1
    assert api.get("clinician2", path).status_code == 404  # not in their care
    assert (
        api.get("clinician", f"/v1/encounters/{uuid.uuid4()}/discharge-summary").status_code == 404
    )
    discharge(api, enc["id"], 1)
    assert api.get("clinician", path).json()["status"] == "signed"
    with factory() as s, s.begin():
        s.execute(
            update(DischargeSummary)
            .where(DischargeSummary.encounter_id == uuid.UUID(enc["id"]))
            .values(sensitivity="mental_health")
        )
    assert api.get("clinician", path).status_code == 404  # withheld, as in the chart
