"""Wards, beds and transfers (CEDA HS03, WF02 step 3; UAT WF02).

A bed holds one patient and a patient holds one bed. A transfer closes the
old occupancy and opens the new one together; discharge closes the last one.
Two people giving the same empty bed at once get one occupancy and one
conflict.
"""

import threading
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import BedOccupancy, Encounter, OutboxEvent
from tests.conftest import Api
from tests.e2e.test_api03_vertical_slice import admit, register
from tests.e2e.test_care_plans import nurse_cares_for
from tests.e2e.test_scheduling import facility


def if_match(version: int) -> dict[str, str]:
    return {"If-Match": f'"{version}"'}


def code(r: Any) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


def ward(api: Api, ward_code: str = "W1", beds: int = 2, **extra: Any) -> dict[str, Any]:
    made = api.post(
        "admin",
        "/v1/wards",
        {
            "facility_id": str(api.tenant.facility_id),
            "code": ward_code,
            "name": f"Ward {ward_code}",
            **extra,
        },
    )
    assert made.status_code == 201, made.text
    out = made.json()
    for n in range(beds):
        isolating = n == beds - 1
        r = api.post(
            "admin",
            f"/v1/wards/{out['id']}/beds",
            {"code": f"{ward_code}-{n + 1}", "isolation_capable": isolating},
        )
        assert r.status_code == 201, r.text
        out = r.json()
    return out


def assign(api: Api, enc: dict[str, Any], bed: str, version: int = 1, **body: Any) -> Any:
    return api.post(
        "nurse", f"/v1/encounters/{enc['id']}/bed", {"bed_id": bed, **body}, **if_match(version)
    )


def transfer(api: Api, enc: dict[str, Any], bed: str, version: int, **body: Any) -> Any:
    return api.post(
        "nurse",
        f"/v1/encounters/{enc['id']}/transfer",
        {"bed_id": bed, **body},
        **if_match(version),
    )


def test_wards_and_beds_are_set_up_by_administrators(
    api: Api, factory: sessionmaker[Session]
) -> None:
    w = ward(api, specialty="general_medicine")
    assert [b["code"] for b in w["beds"]] == ["W1-1", "W1-2"]
    assert [b["isolation_capable"] for b in w["beds"]] == [False, True]
    assert (w["available"], w["occupied"], w["specialty"]) == (2, 0, "general_medicine")
    body = {"facility_id": str(api.tenant.facility_id), "code": "W1", "name": "Again"}
    assert code(api.post("admin", "/v1/wards", body)) == (409, "ward_code_exists")
    again = api.post("admin", f"/v1/wards/{w['id']}/beds", {"code": "W1-1"})
    assert code(again) == (409, "bed_code_exists")
    missing = {**body, "code": "W9", "facility_id": str(uuid.uuid4())}
    assert api.post("admin", "/v1/wards", missing).status_code == 404
    assert api.post("admin", f"/v1/wards/{uuid.uuid4()}/beds", {"code": "X"}).status_code == 404
    # Clinical staff do not set up wards; administrators do not move patients.
    assert code(api.post("nurse", "/v1/wards", {**body, "code": "W2"})) == (
        403,
        "missing_capability",
    )
    assert api.get("scheduler", "/v1/wards").status_code == 403
    [listed] = api.get("registrar", "/v1/wards").json()
    assert listed["id"] == w["id"]
    other = facility(factory, api, "teaching_hospital")
    assert api.get("registrar", f"/v1/wards?facility_id={other}").json() == []


def test_a_transfer_closes_the_old_bed_and_discharge_closes_the_last(
    api: Api, factory: sessionmaker[Session]
) -> None:
    w = ward(api)
    first, second = (b["id"] for b in w["beds"])
    pid = register(api)
    enc = admit(api, pid)
    placed = assign(api, enc, first, reason="Admitted from ED")
    assert placed.status_code == 201, placed.text
    assert (placed.json()["bed_code"], placed.json()["ward_code"]) == ("W1-1", "W1")
    board = api.get("nurse", "/v1/wards").json()[0]
    assert (board["available"], board["occupied"]) == (1, 1)
    assert board["beds"][0]["occupancy"]["patient_id"] == pid

    # Assigning again is refused: a second bed is a transfer.
    assert code(assign(api, enc, second, version=2)) == (409, "already_in_bed")
    assert code(transfer(api, enc, first, 2)) == (422, "same_bed")
    assert code(transfer(api, enc, second, 1)) == (409, "stale_version")
    moved = transfer(api, enc, second, 2, isolation=True, reason="Needs a side room")
    assert moved.status_code == 200, moved.text
    assert moved.json()["previous_id"] == placed.json()["id"]
    assert moved.json()["isolation"] is True

    history = api.get("clinician", f"/v1/encounters/{enc['id']}/movements").json()
    assert [(m["bed_code"], m["end_reason"]) for m in history] == [
        ("W1-1", "transfer"),
        ("W1-2", None),
    ]
    assert history[0]["end_at"] is not None
    board = api.get("nurse", "/v1/wards").json()[0]
    assert [b["occupancy"] is None for b in board["beds"]] == [True, False]

    # Discharge closes the last occupancy and frees the bed.
    summary = {"disposition": "home", "summary": "Recovered"}
    api.post("clinician", f"/v1/encounters/{enc['id']}/discharge-summary", summary)
    out = api.post(
        "clinician",
        f"/v1/encounters/{enc['id']}/discharge",
        {"discharged_at": datetime.now(UTC).isoformat()},
        **if_match(3),
    )
    assert out.status_code == 200, out.text
    history = api.get("clinician", f"/v1/encounters/{enc['id']}/movements").json()
    assert history[-1]["end_reason"] == "discharge"
    assert api.get("nurse", "/v1/wards").json()[0]["occupied"] == 0
    # A finished encounter takes no bed.
    assert code(transfer(api, enc, first, 4)) == (422, "encounter_not_open")
    with factory() as s:
        kinds = s.scalars(
            select(OutboxEvent.event_type).where(
                OutboxEvent.tenant_id == api.tenant.tenant_id,
                OutboxEvent.aggregate_id == uuid.UUID(enc["id"]),
            )
        ).all()
    assert {"encounter.bed_assigned", "encounter.transferred"} <= set(kinds)


def test_beds_that_cannot_take_the_patient_are_refused(
    api: Api, factory: sessionmaker[Session]
) -> None:
    w = ward(api)
    plain, side_room = (b["id"] for b in w["beds"])
    pid = register(api)
    enc = admit(api, pid)
    assert code(transfer(api, enc, plain, 1)) == (409, "no_bed")
    assert code(assign(api, enc, plain, isolation=True)) == (422, "isolation_unavailable")
    assert assign(api, enc, str(uuid.uuid4())).status_code == 404
    other = register(api, "71111111111")
    clinic = admit(api, other, visit="V-OPD", encounter_class="ambulatory")
    assert code(assign(api, clinic, plain)) == (422, "encounter_not_bedded")

    # A bed in another facility is refused.
    elsewhere = facility(factory, api, "teaching_hospital")
    far = api.post(
        "admin", "/v1/wards", {"facility_id": elsewhere, "code": "T1", "name": "Teaching"}
    ).json()
    far = api.post("admin", f"/v1/wards/{far['id']}/beds", {"code": "T1-1"}).json()
    assert code(assign(api, enc, far["beds"][0]["id"])) == (422, "bed_in_another_facility")

    # A closed bed, and a closed ward, take no one.
    bed_version = w["beds"][0]["version"]
    closed = api.post(
        "admin",
        f"/v1/beds/{plain}/status",
        {"status": "closed", "reason": "Deep clean"},
        **if_match(bed_version),
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["available"] == 1
    assert code(assign(api, enc, plain)) == (422, "bed_closed")
    shut = api.post("admin", f"/v1/wards/{w['id']}/status", {"active": False}, **if_match(1))
    assert shut.status_code == 200, shut.text
    assert code(assign(api, enc, side_room)) == (422, "ward_closed")
    api.post("admin", f"/v1/wards/{w['id']}/status", {"active": True}, **if_match(2))

    # An occupied bed cannot be closed, or given to someone else.
    assert assign(api, enc, side_room, isolation=True).status_code == 201
    assert code(
        api.post("admin", f"/v1/beds/{side_room}/status", {"status": "closed"}, **if_match(1))
    ) == (409, "bed_occupied")
    third = admit(api, register(api, "72222222222"), visit="V-3")
    assert code(assign(api, third, side_room)) == (409, "bed_occupied")
    reopened = api.post(
        "admin", f"/v1/beds/{plain}/status", {"status": "available"}, **if_match(bed_version + 1)
    )
    assert reopened.json()["beds"][0]["status_reason"] is None


def test_two_people_give_the_same_empty_bed_at_once(
    api: Api, factory: sessionmaker[Session]
) -> None:
    """CEDA HS03 additional verification: one occupancy and one conflict."""
    w = ward(api, beds=1)
    bed = w["beds"][0]["id"]
    encs = [
        admit(api, register(api), visit="V-A"),
        admit(api, register(api, "71111111111"), visit="V-B"),
    ]
    clients = [TestClient(api.client.app) for _ in range(2)]
    start = threading.Barrier(2)
    results: dict[str, Any] = {}

    def attempt(who: str, client: TestClient, enc: dict[str, Any]) -> None:
        start.wait()
        results[who] = client.post(
            f"/v1/encounters/{enc['id']}/bed",
            json={"bed_id": bed},
            headers=api.headers(who) | if_match(1),
        )

    threads = [
        threading.Thread(target=attempt, args=(who, c, e))
        for who, c, e in zip(("nurse", "registrar"), clients, encs, strict=True)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(r.status_code for r in results.values()) == [201, 409], {
        w: r.text for w, r in results.items()
    }
    loser = next(r for r in results.values() if r.status_code == 409)
    assert loser.json()["error"]["code"] == "bed_occupied"
    with factory() as s:
        open_rows = s.scalar(
            select(func.count())
            .select_from(BedOccupancy)
            .where(BedOccupancy.tenant_id == api.tenant.tenant_id, BedOccupancy.active_marker == 1)
        )
    assert open_rows == 1


def test_the_database_keeps_one_patient_per_bed(api: Api, factory: sessionmaker[Session]) -> None:
    """Even a write that skips the service cannot put two patients in a bed."""
    w = ward(api, beds=1)
    bed = w["beds"][0]["id"]
    first = admit(api, register(api), visit="V-A")
    second = admit(api, register(api, "71111111111"), visit="V-B")
    assert assign(api, first, bed).status_code == 201
    with factory() as s:
        row = s.scalars(
            select(BedOccupancy).where(BedOccupancy.tenant_id == api.tenant.tenant_id)
        ).one()
        s.expunge(row)
    guard = "uq_bed_occupancy_tenant_id_bed_id_active_marker"
    with pytest.raises(IntegrityError, match=guard), factory() as s, s.begin():
        s.add(
            BedOccupancy(
                tenant_id=row.tenant_id,
                id=uuid.uuid7(),
                recorded_at=datetime.now(UTC),
                bed_id=row.bed_id,
                encounter_id=uuid.UUID(second["id"]),
                patient_id=uuid.UUID(second["patient_id"]),
                start_at=datetime.now(UTC),
                isolation=False,
                active_marker=1,
            )
        )


def test_movements_follow_the_chart_rules(api: Api, factory: sessionmaker[Session]) -> None:
    w = ward(api)
    pid = register(api)
    psychiatrist = str(api.tenant.practitioners["psychiatrist"])
    enc = admit(api, pid, responsible_practitioner_id=psychiatrist)
    assign(api, enc, w["beds"][0]["id"])
    assert api.get("clinician2", f"/v1/encounters/{enc['id']}/movements").status_code == 404
    assert api.get("clinician", f"/v1/encounters/{uuid.uuid4()}/movements").status_code == 404
    nurse_cares_for(api, factory, pid)  # in the care team, without mental health access
    assert len(api.get("nurse", f"/v1/encounters/{enc['id']}/movements").json()) == 1
    with factory() as s, s.begin():
        s.execute(
            update(Encounter)
            .where(Encounter.id == uuid.UUID(enc["id"]))
            .values(sensitivity="mental_health")
        )
    assert api.get("nurse", f"/v1/encounters/{enc['id']}/movements").status_code == 404
    assert len(api.get("psychiatrist", f"/v1/encounters/{enc['id']}/movements").json()) == 1
