"""ICRS module 102, patient index (specification section 3.2): duplicate
alerts, search, merge and unmerge, and closure, singly and in batches."""

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import (
    AuditEvent,
    DemographicTransaction,
    MergeLink,
    OutboxEvent,
    Patient,
)
from tests.conftest import Api
from tests.e2e.test_api03_vertical_slice import admit

TODAY = datetime.now(UTC).date()


def person(
    api: Api,
    family: str = "Okafor",
    given: str = "Chidi",
    born: str = "1990-05-01",
    nin: str | None = None,
    sex: str = "male",
) -> dict:
    identifiers = [{"issuer": "NG-NIN", "value": nin, "verified": True}] if nin else []
    r = api.post(
        "registrar",
        "/v1/patients",
        {
            "family_name": family,
            "given_names": given,
            "birth_date": born,
            "administrative_sex": sex,
            "identifiers": identifiers,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def merge(api: Api, prior: dict, survivor: dict, who: str = "steward", **headers: str):  # type: ignore[no-untyped-def]
    return api.post(
        who,
        f"/v1/patients/{prior['id']}/merge",
        {"survivor_id": survivor["id"], "reason": "same person registered twice"},
        **({"If-Match": f'"{prior["version"]}"'} | headers),
    )


def close(api: Api, p: dict, reason: str = "death", exit_date: date = TODAY, **headers: str):  # type: ignore[no-untyped-def]
    return api.post(
        "steward",
        f"/v1/patients/{p['id']}/close",
        {"reason": reason, "exit_date": exit_date.isoformat()},
        **({"If-Match": f'"{p["version"]}"'} | headers),
    )


# -- ICRS 3.2.8: duplicate alerts at registration ------------------------------


def test_registration_alerts_on_probable_duplicates(api: Api) -> None:
    first = person(api, nin="20000000001")
    assert first["possible_duplicates"] == []
    second = person(api, family=" okafor ", nin="20000000002")
    assert second["possible_duplicates"] == [first["id"]]
    other_birthday = person(api, born="1991-05-01")
    assert other_birthday["possible_duplicates"] == []
    other_sex = person(api, sex="female")
    assert other_sex["possible_duplicates"] == []


def test_duplicate_housekeeping_lists_open_groups(api: Api) -> None:
    a, b = person(api), person(api)
    person(api, family="Bello")
    r = api.get("steward", "/v1/patient-index/duplicates")
    assert r.status_code == 200, r.text
    assert r.json() == [
        {
            "family_name": "okafor",
            "birth_date": "1990-05-01",
            "administrative_sex": "male",
            "patient_ids": sorted([a["id"], b["id"]]),
        }
    ]
    assert merge(api, a, b).status_code == 200
    assert api.get("steward", "/v1/patient-index/duplicates").json() == []
    assert api.get("registrar", "/v1/patient-index/duplicates").status_code == 403


# -- ICRS 3.2.3, 3.2.34: search ---------------------------------------------------


def test_search_by_nin_and_by_name(api: Api, factory: sessionmaker[Session]) -> None:
    a = person(api, family="Okafor", given="Chidi", nin="21000000001")
    person(api, family="Okonkwo", given="Ada", born="1975-01-02", sex="female")
    by_nin = api.get("registrar", "/v1/patient-index?nin=210 0000 0001")
    assert by_nin.status_code == 200, by_nin.text
    [hit] = by_nin.json()
    assert hit["id"] == a["id"]
    assert hit["identifiers"][0]["value"] == "*******0001"  # registrars see it masked
    steward = api.get("steward", "/v1/patient-index?nin=21000000001").json()
    assert steward[0]["identifiers"][0]["value"] == "21000000001"

    prefix = api.get("clinician", "/v1/patient-index?family_name=Ok").json()
    assert {p["family_name"] for p in prefix} == {"Okafor", "Okonkwo"}
    narrowed = api.get(
        "clinician", "/v1/patient-index?family_name=Ok&given_name=Ad&birth_date=1975-01-02"
    ).json()
    assert [p["given_names"] for p in narrowed] == ["Ada"]
    assert api.get("clinician", "/v1/patient-index?family_name=O%25").json() == []
    assert len(api.get("clinician", "/v1/patient-index?family_name=Ok&limit=1").json()) == 1

    with factory() as s:
        audits = s.execute(
            select(AuditEvent.action).where(
                AuditEvent.tenant_id == api.tenant.tenant_id,
                AuditEvent.resource_type == "patient_index",
            )
        ).scalars()
        assert list(audits).count("patient_index.search") == 6


def test_search_needs_criteria_and_capability(api: Api, factory: sessionmaker[Session]) -> None:
    r = api.get("registrar", "/v1/patient-index")
    assert (r.status_code, r.json()["error"]["code"]) == (422, "search_criteria_required")
    r = api.get("registrar", "/v1/patient-index?nin=123")
    assert (r.status_code, r.json()["error"]["code"]) == (422, "bad_identifier")
    r = api.get("nurse", "/v1/patient-index?family_name=Okafor")
    assert (r.status_code, r.json()["error"]["code"]) == (403, "missing_capability")
    with factory() as s:
        denied = s.execute(
            select(AuditEvent).where(
                AuditEvent.tenant_id == api.tenant.tenant_id, AuditEvent.outcome == "denied"
            )
        ).scalar_one()
        assert denied.resource_type == "patient_index"


# -- ICRS 3.2.12, 3.2.33: merge and unmerge -------------------------------------------


def test_merge_moves_identifiers_and_combines_the_chart(
    api: Api, factory: sessionmaker[Session]
) -> None:
    prior = person(api, nin="22000000001")
    survivor = person(api)
    encounter = admit(api, prior["id"], visit="V-P1")
    admit(api, survivor["id"], visit="V-S1")

    r = merge(api, prior, survivor)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["prior"]["status"] == "merged"
    assert body["prior"]["merged_into"] == survivor["id"]
    assert body["prior"]["identifiers"] == []
    assert [i["value"] for i in body["survivor"]["identifiers"]] == ["22000000001"]

    chart = api.get("clinician", f"/v1/patients/{survivor['id']}/chart").json()
    assert chart["merged_from"] == [prior["id"]]
    assert {e["visit_number"] for e in chart["encounters"]} == {"V-P1", "V-S1"}
    assert encounter["id"] in {e["id"] for e in chart["encounters"]}

    found = api.get("steward", "/v1/patient-index?nin=22000000001").json()
    assert {(p["id"], p["merged_into"]) for p in found} == {
        (prior["id"], survivor["id"]),
        (survivor["id"], None),
    }
    r = admit_raw(api, prior["id"])
    assert (r.status_code, r.json()["error"]["code"]) == (409, "patient_not_admissible")

    with factory() as s:
        tid = api.tenant.tenant_id
        events = s.execute(
            select(OutboxEvent.event_type).where(OutboxEvent.tenant_id == tid)
        ).scalars()
        assert "patient.merged" in list(events)
        reasons = s.execute(
            select(
                DemographicTransaction.patient_id, DemographicTransaction.transaction_user
            ).where(
                DemographicTransaction.tenant_id == tid,
                DemographicTransaction.change_reason == "merge",
            )
        ).all()
        assert {str(p) for p, _ in reasons} == {prior["id"], survivor["id"]}
        assert {u for _, u in reasons} == {api.tenant.subject("steward")}


def admit_raw(api: Api, patient_id: str):  # type: ignore[no-untyped-def]
    return api.post(
        "registrar",
        "/v1/encounters",
        {
            "patient_id": patient_id,
            "facility_id": str(api.tenant.facility_id),
            "responsible_practitioner_id": str(api.tenant.practitioners["clinician"]),
            "visit_authority": "PILOT",
            "visit_number": "V-X",
            "service": "general_medicine",
            "admitted_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        },
    )


def test_merge_chain_reaches_the_last_survivor(api: Api) -> None:
    a, b, c = person(api), person(api), person(api)
    admit(api, a["id"], visit="V-A")
    admit(api, c["id"], visit="V-C")
    assert merge(api, a, b).status_code == 200
    assert merge(api, b, c).status_code == 200  # a survivor's version is unchanged by a merge
    chart = api.get("clinician", f"/v1/patients/{c['id']}/chart").json()
    assert sorted(chart["merged_from"]) == sorted([a["id"], b["id"]])
    assert {e["visit_number"] for e in chart["encounters"]} == {"V-A", "V-C"}


def test_merge_is_refused_when_unsafe(api: Api) -> None:
    a = person(api, nin="23000000001")
    b = person(api, nin="23000000002")
    c = person(api)

    def code(r) -> tuple[int, str]:  # type: ignore[no-untyped-def]
        return r.status_code, r.json()["error"]["code"]

    assert code(merge(api, a, a)) == (422, "merge_into_self")
    assert code(merge(api, a, b)) == (422, "identifier_mismatch")
    assert code(merge(api, a, c, **{"If-Match": ""})) == (428, "precondition_required")
    assert code(merge(api, a, c, **{"If-Match": '"9"'})) == (409, "stale_version")
    assert code(merge(api, a, {"id": str(uuid.uuid4())})) == (404, "not_found")
    assert code(merge(api, a, c, who="registrar")) == (404, "not_found")  # concealed
    assert code(merge(api, a, c, who="unlinked_steward")) == (403, "no_practitioner")
    assert merge(api, a, c).status_code == 200
    a["version"] += 1
    assert code(merge(api, a, b)) == (422, "not_mergeable")
    assert code(merge(api, b, a)) == (422, "survivor_not_open")


def test_merge_replays_with_the_same_key(api: Api) -> None:
    a, b = person(api), person(api)
    first = merge(api, a, b, key="merge-key-1")
    again = merge(api, a, b, key="merge-key-1")
    assert again.status_code == 200
    assert again.headers["Idempotent-Replay"] == "true"
    assert again.json() == first.json()


def test_unmerge_restores_both_records(api: Api, factory: sessionmaker[Session]) -> None:
    prior = person(api, nin="24000000001")
    survivor = person(api)
    admit(api, prior["id"], visit="V-P2")
    admit(api, survivor["id"], visit="V-S2")
    link = merge(api, prior, survivor).json()["merge_link_id"]

    r = api.post("steward", f"/v1/merge-links/{link}/unmerge", {"reason": "different people"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["prior"]["status"] == "active"
    assert body["prior"]["merged_into"] is None
    assert [i["value"] for i in body["prior"]["identifiers"]] == ["24000000001"]
    assert body["survivor"]["identifiers"] == []

    chart = api.get("clinician", f"/v1/patients/{survivor['id']}/chart").json()
    assert chart["merged_from"] == []
    assert {e["visit_number"] for e in chart["encounters"]} == {"V-S2"}

    def code(r) -> tuple[int, str]:  # type: ignore[no-untyped-def]
        return r.status_code, r.json()["error"]["code"]

    again = api.post("steward", f"/v1/merge-links/{link}/unmerge", {"reason": "twice"})
    assert code(again) == (409, "not_reversible")
    reversal = body["merge_link_id"]
    assert code(
        api.post("steward", f"/v1/merge-links/{reversal}/unmerge", {"reason": "x" * 3})
    ) == (
        409,
        "not_reversible",
    )
    missing = api.post("steward", f"/v1/merge-links/{uuid.uuid4()}/unmerge", {"reason": "nope"})
    assert code(missing) == (404, "not_found")
    unlinked = api.post("unlinked_steward", f"/v1/merge-links/{link}/unmerge", {"reason": "x" * 3})
    assert code(unlinked) == (403, "no_practitioner")

    with factory() as s:
        actions = s.execute(
            select(MergeLink.action, MergeLink.reconciliation_status).where(
                MergeLink.tenant_id == api.tenant.tenant_id
            )
        ).all()
        assert sorted(actions) == [("merge", "reversed"), ("unmerge", "unmerged")]


def test_legacy_merge_without_recorded_changes_cannot_be_reversed(
    api: Api, factory: sessionmaker[Session]
) -> None:
    a, b = person(api), person(api)
    link = uuid.uuid7()
    with factory() as s, s.begin():
        s.add(
            MergeLink(
                tenant_id=api.tenant.tenant_id,
                id=link,
                recorded_at=datetime.now(UTC),
                prior_id=uuid.UUID(a["id"]),
                survivor_id=uuid.UUID(b["id"]),
                action="merge",
                reviewer_id=api.tenant.practitioners["steward"],
                reason="legacy Manage_Trans row",
                reconciliation_status="merged",
                source_system="legacy-pas",
            )
        )
        s.get_one(Patient, (api.tenant.tenant_id, uuid.UUID(a["id"]))).status = "merged"
    r = api.post("steward", f"/v1/merge-links/{link}/unmerge", {"reason": "try it"})
    assert (r.status_code, r.json()["error"]["code"]) == (409, "not_reversible")


# -- ICRS 3.2.18-3.2.20: closure -----------------------------------------------------


def test_close_for_death_and_for_moving_away(api: Api, factory: sessionmaker[Session]) -> None:
    dead = person(api)
    r = close(api, dead, "death", TODAY - timedelta(days=1))
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["date_of_exit"]) == (
        "deceased",
        (TODAY - timedelta(days=1)).isoformat(),
    )
    moved = person(api, family="Bello")
    r = close(api, moved, "moved_away")
    assert r.json()["status"] == "closed"
    with factory() as s:
        row = s.get_one(Patient, (api.tenant.tenant_id, uuid.UUID(dead["id"])))
        assert (row.death_date, row.death_notification_status) == (
            TODAY - timedelta(days=1),
            "notified",
        )
        who = s.execute(
            select(DemographicTransaction.transaction_user, DemographicTransaction.delta).where(
                DemographicTransaction.tenant_id == api.tenant.tenant_id,
                DemographicTransaction.change_reason == "closure:moved_away",
            )
        ).one()
        assert who[0] == api.tenant.subject("steward")
        assert who[1]["status"] == ["active", "closed"]


def test_close_is_refused_when_invalid(api: Api) -> None:
    p = person(api, born="2000-01-01")

    def code(r) -> tuple[int, str]:  # type: ignore[no-untyped-def]
        return r.status_code, r.json()["error"]["code"]

    assert code(close(api, p, exit_date=TODAY + timedelta(days=1))) == (422, "bad_closure_date")
    assert code(close(api, p, exit_date=date(1999, 12, 31))) == (422, "bad_closure_date")
    assert code(close(api, p, **{"If-Match": ""})) == (428, "precondition_required")
    assert close(api, p).status_code == 200
    p["version"] += 1
    assert code(close(api, p)) == (422, "not_closable")


def test_batch_closure_reports_each_item(api: Api) -> None:
    a, b, c = person(api), person(api, family="Bello"), person(api, family="Eze")
    assert close(api, c, "discharged").status_code == 200
    items = [
        {"patient_id": a["id"], "reason": "death", "exit_date": TODAY.isoformat()},
        {"patient_id": str(uuid.uuid4()), "reason": "death", "exit_date": TODAY.isoformat()},
        {"patient_id": c["id"], "reason": "death", "exit_date": TODAY.isoformat()},
        {
            "patient_id": b["id"],
            "reason": "moved_away",
            "exit_date": (TODAY + timedelta(days=3)).isoformat(),
        },
    ]
    r = api.post("steward", "/v1/patient-index/closures", {"items": items})
    assert r.status_code == 200, r.text
    assert r.json() == {
        "closed": 1,
        "results": [
            {"patient_id": a["id"], "outcome": "closed", "status": "deceased"},
            {"patient_id": items[1]["patient_id"], "outcome": "not_found"},
            {"patient_id": c["id"], "outcome": "not_closable"},
            {"patient_id": b["id"], "outcome": "bad_closure_date"},
        ],
    }
    denied = api.post("registrar", "/v1/patient-index/closures", {"items": items[:1]})
    assert denied.status_code == 403
