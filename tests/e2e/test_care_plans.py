"""Conditions and care plans (CEDA HS12; SA-08).

HS12 acceptance: a revised plan changes future sessions while retaining the
exact version used for each completed intervention; a completed treatment
cycle keeps the original plan reference after a later plan amendment;
unresolved schedule conflicts are held for a named reviewer."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import LegitimateRelationship, Task
from tests.conftest import Api
from tests.e2e.test_api03_vertical_slice import admit, register

NOW = datetime.now(UTC)


def if_match(version: int) -> dict[str, str]:
    return {"If-Match": f'"{version}"'}


def code(r: Any) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


def plan(api: Api, pid: str, owner: str = "clinician", **revision: Any) -> Any:
    rev = {
        "effective_from": (NOW + timedelta(minutes=5)).isoformat(),
        "session_type": "dialysis",
        "interval_days": 2,
        "sessions": 4,
        "instructions": "Haemodialysis 4 hours, dry weight 68 kg, heparin per protocol",
        "protocol_code": "HD-STD-01",
        **revision,
    }
    return api.post(
        "clinician",
        "/v1/care-plans",
        {
            "patient_id": pid,
            "pathway": "renal",
            "title": "Maintenance haemodialysis",
            "owner_id": str(api.tenant.practitioners[owner]),
            "review_date": (NOW + timedelta(days=90)).date().isoformat(),
            "revision": rev,
        },
    )


def nurse_cares_for(api: Api, factory: sessionmaker[Session], pid: str) -> None:
    with factory() as s, s.begin():
        s.add(
            LegitimateRelationship(
                tenant_id=api.tenant.tenant_id,
                id=uuid.uuid7(),
                recorded_at=NOW,
                patient_id=uuid.UUID(pid),
                practitioner_id=api.tenant.practitioners["nurse"],
                start_at=NOW - timedelta(minutes=1),
                creation_reason_code="dialysis_unit",
            )
        )


def test_conditions_build_the_problem_list(api: Api) -> None:
    pid = register(api)
    admit(api, pid)
    body = {
        "code_system": "http://hl7.org/fhir/sid/icd-10",
        "code": "N18.5",
        "display": "Chronic kidney disease, stage 5",
        "onset_date": "2025-06-01",
        "register_code": "renal",
    }
    made = api.post("clinician", f"/v1/patients/{pid}/conditions", body)
    assert made.status_code == 201, made.text
    assert (made.json()["register_code"], made.json()["certainty"]) == ("renal", "confirmed")
    api.post(
        "clinician",
        f"/v1/patients/{pid}/conditions",
        {**body, "code": "E11", "display": "Type 2 diabetes", "certainty": "refuted"},
    )
    assert api.post("clinician2", f"/v1/patients/{pid}/conditions", body).status_code == 404
    chart = api.get("clinician", f"/v1/patients/{pid}/chart").json()
    assert [c["code"] for c in chart["conditions"]] == ["N18.5"]  # refuted is not listed


def test_a_revision_changes_future_sessions_and_completed_ones_keep_theirs(
    api: Api, factory: sessionmaker[Session]
) -> None:
    pid = register(api)
    admit(api, pid)
    condition = api.post(
        "clinician",
        f"/v1/patients/{pid}/conditions",
        {"code_system": "http://hl7.org/fhir/sid/icd-10", "code": "N18.5", "display": "CKD 5"},
    ).json()
    made = plan(api, pid)
    assert made.status_code == 201, made.text
    p = made.json()
    assert p["current_revision"] == 1 and len(p["cycles"]) == 4
    assert {c["revision_number"] for c in p["cycles"]} == {1}
    first, second, third, _ = p["cycles"]

    nurse_cares_for(api, factory, pid)
    done = api.post(
        "nurse", f"/v1/plan-cycles/{first['id']}/complete", {"note": "Uneventful"}, **if_match(1)
    )
    assert done.status_code == 200, done.text
    assert code(
        api.post("nurse", f"/v1/plan-cycles/{first['id']}/complete", {}, **if_match(2))
    ) == (422, "invalid_transition")

    # Revise from the third session on: dry weight changes, sessions now daily.
    revise = f"/v1/care-plans/{p['id']}/revisions"
    change = {
        "effective_from": third["scheduled_at"],
        "session_type": "dialysis",
        "interval_days": 1,
        "sessions": 3,
        "instructions": "Haemodialysis 4 hours, dry weight 66 kg",
        "reason": "Fluid overload between sessions",
    }
    assert code(api.post("clinician", revise, change)) == (428, "precondition_required")
    past = {**change, "effective_from": (NOW - timedelta(days=1)).isoformat()}
    assert code(api.post("clinician", revise, past, **if_match(1))) == (422, "bad_effective_time")
    revised = api.post("clinician", revise, change, **if_match(1))
    assert revised.status_code == 200, revised.text
    out = revised.json()
    assert out["current_revision"] == 2
    assert [r["instructions"] for r in out["revisions"]] == [
        "Haemodialysis 4 hours, dry weight 68 kg, heparin per protocol",  # unchanged
        "Haemodialysis 4 hours, dry weight 66 kg",
    ]
    cycles = {c["id"]: c for c in out["cycles"]}
    assert (cycles[first["id"]]["status"], cycles[first["id"]]["revision_number"]) == (
        "completed",
        1,
    )
    assert (cycles[second["id"]]["status"], cycles[second["id"]]["revision_number"]) == (
        "scheduled",
        1,  # before the revision takes effect: the original instructions
    )
    assert cycles[third["id"]]["status"] == "cancelled"
    assert cycles[third["id"]]["outcome_note"] == "replaced by revision 2"
    new = [c for c in out["cycles"] if c["revision_number"] == 2]
    assert len(new) == 3 and all(c["status"] == "scheduled" for c in new)

    # Completed after the amendment, the second session still keeps revision 1.
    api.post("nurse", f"/v1/plan-cycles/{second['id']}/complete", {}, **if_match(1))
    read = api.get("clinician", f"/v1/care-plans/{p['id']}")
    assert read.status_code == 200
    kept = next(c for c in read.json()["cycles"] if c["id"] == second["id"])
    assert (kept["status"], kept["revision_number"]) == ("completed", 1)
    [summary] = api.get("clinician", f"/v1/patients/{pid}/chart").json()["care_plans"]
    assert (summary["current_revision"], summary["next_session"]) == (2, new[0]["scheduled_at"])
    assert api.get("clinician2", f"/v1/care-plans/{p['id']}").status_code == 404
    assert api.get("clinician", f"/v1/care-plans/{uuid.uuid4()}").status_code == 404

    other = register(api, "66666666666")
    admit(api, other, visit="V-OTHER")
    wrong = {
        "patient_id": other,
        "condition_id": condition["id"],  # recorded for the first patient
        "pathway": "renal",
        "title": "Wrong patient",
        "owner_id": str(api.tenant.practitioners["clinician"]),
        "review_date": "2027-01-01",
        "revision": {
            "effective_from": (NOW + timedelta(minutes=5)).isoformat(),
            "session_type": "review",
            "interval_days": 7,
            "sessions": 1,
            "instructions": "Review",
        },
    }
    assert code(api.post("clinician", "/v1/care-plans", wrong)) == (
        422,
        "condition_patient_mismatch",
    )


def test_a_clash_is_held_for_the_plan_owner_and_a_discontinued_plan_stops(
    api: Api, factory: sessionmaker[Session]
) -> None:
    pid = register(api)
    admit(api, pid)
    tomorrow = (NOW + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    plan(api, pid, effective_from=tomorrow.isoformat(), interval_days=1, sessions=3)
    review = {
        "effective_from": (tomorrow + timedelta(hours=5)).isoformat(),
        "session_type": "review",
        "interval_days": 30,
        "sessions": 1,
        "instructions": "Diabetes annual review",
    }
    clashing = plan(api, pid, **review)
    assert clashing.status_code == 201, clashing.text
    c = clashing.json()
    [held] = c["cycles"]
    assert held["status"] == "held"
    with factory() as s:
        task = s.execute(
            select(Task.assignee_id, Task.status).where(Task.origin_id == uuid.UUID(held["id"]))
        ).one()
    assert task == (api.tenant.practitioners["clinician"], "open")  # the named reviewer
    assert code(
        api.post("clinician", f"/v1/plan-cycles/{held['id']}/complete", {}, **if_match(1))
    ) == (422, "invalid_transition")
    released = api.post(
        "clinician",
        f"/v1/plan-cycles/{held['id']}/release",
        {"note": "Both fit on the same day: review after dialysis"},
        **if_match(1),
    )
    assert released.status_code == 200, released.text
    assert released.json()["cycles"][0]["status"] == "scheduled"
    with factory() as s:
        assert s.scalar(select(Task.status).where(Task.origin_id == uuid.UUID(held["id"]))) == (
            "completed"
        )

    # A clash on a plan someone else owns is theirs to resolve.
    theirs = plan(api, pid, owner="clinician2", **review).json()
    [their_held] = theirs["cycles"]
    assert code(
        api.post(
            "clinician",
            f"/v1/plan-cycles/{their_held['id']}/release",
            {"note": "mine?"},
            **if_match(1),
        )
    ) == (403, "not_plan_owner")

    # Discontinuing ends every session still to come and its clash task.
    stop = api.post(
        "clinician",
        f"/v1/care-plans/{theirs['id']}/discontinue",
        {"reason": "Moved to another unit"},
        **if_match(1),
    )
    assert stop.status_code == 200, stop.text
    assert (stop.json()["status"], stop.json()["cycles"][0]["status"]) == (
        "discontinued",
        "cancelled",
    )
    with factory() as s:
        assert (
            s.scalar(select(Task.status).where(Task.origin_id == uuid.UUID(their_held["id"])))
            == "cancelled"
        )
    path = f"/v1/care-plans/{theirs['id']}"
    assert code(
        api.post("clinician", f"{path}/discontinue", {"reason": "again"}, **if_match(2))
    ) == (422, "plan_not_active")
    assert code(
        api.post("clinician", f"{path}/revisions", {**review, "reason": "x" * 3}, **if_match(2))
    ) == (422, "plan_not_active")
