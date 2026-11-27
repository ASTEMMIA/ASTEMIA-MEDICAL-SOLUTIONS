"""Identity stewardship (UG02, WF01 steps 1 and 4, CEDA E3, HS02): search
before registering, likely duplicates held for review, review tasks, and merge
and unmerge with lineage. Clinical records never move; reads follow merges."""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import (
    AuditEvent,
    DuplicateCandidate,
    MergeLink,
    OutboxEvent,
    PatientIdentifier,
)
from tests.conftest import Api
from tests.e2e.test_api03_vertical_slice import admit, order, register

PERSON = {
    "family_name": "Adeyemi",
    "given_names": "Folake Ngozi",
    "birth_date": "1984-03-09",
    "administrative_sex": "female",
    "mother_name": "Bisi Adeyemi",
}


def if_match(version: int) -> dict[str, str]:
    return {"If-Match": f'"{version}"'}


def create(api: Api, body: dict[str, Any]) -> dict[str, Any]:
    r = api.post("registrar", "/v1/patients", body)
    assert r.status_code == 201, r.text
    return r.json()


def merge(api: Api, prior: dict[str, Any], survivor_id: str, **extra: Any) -> Any:
    return api.post(
        "steward",
        f"/v1/patients/{prior['id']}/merge",
        {"survivor_id": survivor_id, "reason": "same person, confirmed at the desk", **extra},
        **if_match(prior["version"]),
    )


def count(factory: sessionmaker[Session], model: Any, *where: Any) -> int:
    with factory() as s:
        return s.scalar(select(func.count()).select_from(model).where(*where)) or 0


# --- WF01 step 1: search -----------------------------------------------------------


def test_search_shows_masked_candidates_and_is_audited(
    api: Api, factory: sessionmaker[Session]
) -> None:
    pid = register(api)
    probe = {**PERSON, "family_name": "Adeyemmi", "mother_name": None}
    r = api.post("registrar", "/v1/patients/match", probe)
    assert r.status_code == 200, r.text
    [c] = r.json()["candidates"]
    assert c["id"] == pid and c["band"] == "possible" and c["score"] == 70
    assert c["reasons"] == [
        "birth_date",
        "family_name_sounds_like",
        "given_name",
        "administrative_sex",
    ]
    assert (c["family_name"], c["given_initial"], c["birth_year"]) == ("Adeyemi", "F", 1984)
    assert "given_names" not in c and "birth_date" not in c  # only enough to tell people apart
    assert c["identifiers"][0]["value"] == "*******8901"  # the registrar sees it masked
    steward = api.post("steward", "/v1/patients/match", probe).json()["candidates"][0]
    assert steward["identifiers"][0]["value"] == "12345678901"
    by_number = api.post(
        "registrar",
        "/v1/patients/match",
        {
            **probe,
            "family_name": "Someone",
            "given_names": "Else",
            "birth_date": "2001-01-01",
            "identifiers": [{"issuer": "NG-NIN", "value": "123 456 789 01"}],
        },
    ).json()["candidates"]
    assert [(x["id"], x["score"], x["reasons"]) for x in by_number] == [(pid, 100, ["identifier"])]
    nobody = api.post(
        "registrar",
        "/v1/patients/match",
        {**probe, "family_name": "Nwosu", "given_names": "Ike", "birth_date": "1950-05-05"},
    )
    assert nobody.json() == {"candidates": []}
    tid = api.tenant.tenant_id
    assert (
        count(
            factory, AuditEvent, AuditEvent.tenant_id == tid, AuditEvent.action == "patient.search"
        )
        == 4
    )
    denied = api.post("nurse", "/v1/patients/match", probe)
    assert denied.status_code == 403


# --- UG02: likely duplicates are held at registration ------------------------------


def test_likely_duplicate_needs_acknowledgement(api: Api, factory: sessionmaker[Session]) -> None:
    first = create(api, PERSON)
    held = api.post("registrar", "/v1/patients", PERSON)
    assert held.status_code == 409
    err = held.json()["error"]
    assert err["code"] == "possible_duplicate"
    assert [c["id"] for c in err["details"]["candidates"]] == [first["id"]]
    assert err["details"]["candidates"][0]["band"] == "likely"
    no_reason = api.post(
        "registrar", "/v1/patients", {**PERSON, "acknowledged_candidates": [first["id"]]}
    )
    assert no_reason.status_code == 422
    assert no_reason.json()["error"]["code"] == "distinct_reason_required"
    wrong = api.post(
        "registrar",
        "/v1/patients",
        {
            **PERSON,
            "acknowledged_candidates": [str(uuid.uuid4())],
            "distinct_reason": "twin sister",
        },
    )
    assert wrong.json()["error"]["code"] == "possible_duplicate"
    second = create(
        api,
        {
            **PERSON,
            "acknowledged_candidates": [first["id"]],
            "distinct_reason": "twin sister, seen together",
        },
    )
    # The registrar's word is not the last: a steward reviews the pair.
    tasks = api.get("steward", "/v1/identity-review-tasks")
    assert tasks.status_code == 200, tasks.text
    [task] = tasks.json()
    assert (task["origin"], task["note"], task["score"]) == (
        "registration",
        "twin sister, seen together",
        90,
    )
    assert {r["id"] for r in task["records"]} == {first["id"], second["id"]}
    assert api.get("registrar", "/v1/identity-review-tasks").status_code == 403
    tid = api.tenant.tenant_id
    assert (
        count(
            factory,
            OutboxEvent,
            OutboxEvent.tenant_id == tid,
            OutboxEvent.event_type == "identity_review.opened",
        )
        == 1
    )


def test_possible_duplicate_registers_and_opens_a_review(api: Api) -> None:
    first = create(api, PERSON)
    similar = create(api, {**PERSON, "family_name": "Adeyemmi", "mother_name": None})
    [task] = api.get("steward", "/v1/identity-review-tasks").json()
    assert {r["id"] for r in task["records"]} == {first["id"], similar["id"]}
    assert task["note"] is None and not task["resolved"]

    path = f"/v1/identity-review-tasks/{task['id']}/resolve"
    body = {"resolution": "distinct", "reason": "different mothers, checked documents"}
    assert api.post("steward", path, body).status_code == 428  # If-Match is required
    assert api.post("registrar", path, body, **if_match(1)).status_code == 403
    done = api.post("steward", path, body, **if_match(1))
    assert done.status_code == 200, done.text
    out = done.json()
    assert out["resolved"] and out["resolution"] == "distinct" and out["version"] == 2
    assert out["resolved_by_id"] == str(api.tenant.practitioners["steward"])
    assert done.headers["ETag"] == '"2"'
    again = api.post("steward", path, body, **if_match(1))
    assert again.json()["error"]["code"] == "stale_version"
    again = api.post("steward", path, body, **if_match(2))
    assert again.json()["error"]["code"] == "review_already_resolved"
    assert api.get("steward", "/v1/identity-review-tasks").json() == []
    [closed] = api.get("steward", "/v1/identity-review-tasks?resolved=true").json()
    assert closed["id"] == task["id"]


# --- HS02 / E3: merge and unmerge --------------------------------------------------


def test_unidentified_arrival_merged_into_registered_patient_and_back(
    api: Api, factory: sessionmaker[Session]
) -> None:
    tid = api.tenant.tenant_id
    arrival = create(
        api,
        {
            "family_name": "Unknown",
            "given_names": "Female",
            "birth_date": "1984-01-01",
            "birth_date_precision": "year",
            "administrative_sex": "female",
            "temporary": True,
            "identifiers": [
                {"issuer": "LOCAL-MRN", "value": "ER-0001", "identifier_type": "temporary"}
            ],
        },
    )
    enc = admit(api, arrival["id"], visit="V-ER-1")
    known = create(
        api,
        {**PERSON, "identifiers": [{"issuer": "NG-NIN", "value": "12345678901", "verified": True}]},
    )
    # The clinician cares for the arrival, not (yet) for the registered record.
    assert api.get("clinician", f"/v1/patients/{known['id']}/chart").status_code == 404

    merged = merge(api, arrival, known["id"])
    assert merged.status_code == 200, merged.text
    link = merged.json()
    assert (link["action"], link["reversible"], link["reconciliation_status"]) == (
        "merge",
        True,
        "pending",
    )
    assert link["reviewer_id"] == str(api.tenant.practitioners["steward"])
    assert link["prior"]["status"] == "merged" and link["prior"]["identifiers"] == []
    survivor = link["survivor"]
    assert {(i["issuer"], i["value"], i["identifier_type"]) for i in survivor["identifiers"]} == {
        ("NG-NIN", "12345678901", "current"),
        ("LOCAL-MRN", "ER-0001", "temporary"),  # the temporary identity keeps its number
    }
    assert ("alias", "Unknown") in {(n["name_type"], n["family_name"]) for n in survivor["names"]}

    # Reads follow the merge: the encounter stays on the arrival's record, with
    # its author, and the surviving chart shows it.
    chart = api.get("clinician", f"/v1/patients/{known['id']}/chart")
    assert chart.status_code == 200, chart.text
    assert [e["id"] for e in chart.json()["encounters"]] == [enc["id"]]
    assert chart.json()["merged_records"] == [arrival["id"]]
    gone = api.get("clinician", f"/v1/patients/{arrival['id']}/chart")
    assert gone.status_code == 409
    assert gone.json()["error"]["details"] == {"survivor_id": known["id"]}
    o = order(api, known["id"], enc["id"])  # the open encounter still takes orders
    assert o["patient_id"] == arrival["id"]
    no_admit = api.post(
        "registrar",
        "/v1/encounters",
        {
            "patient_id": arrival["id"],
            "facility_id": str(api.tenant.facility_id),
            "responsible_practitioner_id": str(api.tenant.practitioners["clinician"]),
            "visit_authority": "PILOT",
            "visit_number": "V-ER-2",
            "service": "general_medicine",
            "admitted_at": enc["period_start"],
        },
    )
    assert no_admit.json()["error"]["code"] == "patient_not_admissible"
    found = api.post(
        "steward",
        "/v1/patients/match",
        {**PERSON, "family_name": "Unknown", "given_names": "Female", "mother_name": None},
    ).json()["candidates"]
    assert found[0]["id"] == known["id"]  # found by the alias
    with factory() as s:
        orig = s.scalars(
            select(PatientIdentifier).where(
                PatientIdentifier.tenant_id == tid, PatientIdentifier.value == "ER-0001"
            )
        ).all()
    assert sorted((i.patient_id.hex, i.active_marker) for i in orig) == sorted(
        [(arrival["id"].replace("-", ""), None), (known["id"].replace("-", ""), 1)]
    )
    assert len({i.author_id for i in orig}) == 1  # the original author is kept

    again = api.post(
        "steward",
        f"/v1/patients/{arrival['id']}/merge",
        {"survivor_id": known["id"], "reason": "again"},
        **if_match(2),
    )
    assert again.json()["error"]["code"] == "prior_not_mergeable"

    # ADT A40 lineage: the merge is reversed exactly.
    path = f"/v1/merge-links/{link['id']}/unmerge"
    body = {"reason": "wrong patient, wristband misread"}
    assert api.post("registrar", path, body, **if_match(1)).status_code == 403
    undone = api.post("steward", path, body, **if_match(1))
    assert undone.status_code == 200, undone.text
    out = undone.json()
    assert out["action"] == "unmerged" and out["version"] == 2
    assert out["prior"]["status"] == "temporary"
    assert out["prior"]["identifiers"][0]["value"] == "ER-0001"
    assert {i["issuer"] for i in out["survivor"]["identifiers"]} == {"NG-NIN"}
    assert "alias" not in {n["name_type"] for n in out["survivor"]["names"]}
    back = api.get("clinician", f"/v1/patients/{arrival['id']}/chart").json()
    assert [x["id"] for x in back["orders"]] == [o["id"]]  # the order went back with its encounter
    assert api.get("clinician", f"/v1/patients/{known['id']}/chart").status_code == 404
    twice = api.post("steward", path, body, **if_match(2))
    assert twice.json()["error"]["code"] == "already_unmerged"
    with factory() as s:
        events = s.scalars(
            select(OutboxEvent.event_type).where(
                OutboxEvent.tenant_id == tid, OutboxEvent.event_type.like("patient.%merged")
            )
        ).all()
        audits = s.scalars(
            select(AuditEvent.patient_id).where(
                AuditEvent.tenant_id == tid, AuditEvent.action == "patient.merge"
            )
        ).all()
    assert sorted(events) == ["patient.merged", "patient.unmerged"]
    assert len(audits) == 2  # both records carry the merge in their audit trail


def test_merge_refusals(api: Api, factory: sessionmaker[Session]) -> None:
    a = create(
        api,
        {**PERSON, "identifiers": [{"issuer": "NG-NIN", "value": "11111111111", "verified": True}]},
    )
    b = create(
        api,
        {**PERSON, "identifiers": [{"issuer": "NG-NIN", "value": "22222222222", "verified": True}]},
    )
    clash = merge(api, a, b["id"])
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "conflicting_identifiers"
    assert merge(api, a, a["id"]).json()["error"]["code"] == "self_merge"
    stale = api.post(
        "steward",
        f"/v1/patients/{a['id']}/merge",
        {"survivor_id": b["id"], "reason": "x" * 3},
        **if_match(9),
    )
    assert stale.json()["error"]["code"] == "stale_version"
    assert (
        api.post(
            "registrar", f"/v1/patients/{a['id']}/merge", {"survivor_id": b["id"], "reason": "abc"}
        ).status_code
        == 403
    )
    unlinked = api.post(
        "unlinked_steward",
        f"/v1/patients/{a['id']}/merge",
        {"survivor_id": b["id"], "reason": "abc"},
        **if_match(1),
    )
    assert unlinked.status_code == 403 and unlinked.json()["error"]["code"] == "no_practitioner"
    assert count(factory, MergeLink, MergeLink.tenant_id == api.tenant.tenant_id) == 0


def test_same_issuer_numbers_are_kept_and_reviews_close_on_merge(
    api: Api, factory: sessionmaker[Session]
) -> None:
    mrn = {"issuer": "LOCAL-MRN", "identifier_type": "current"}
    a = create(api, {**PERSON, "identifiers": [{**mrn, "value": "MRN-1"}]})
    b = create(
        api,
        {
            **PERSON,
            "identifiers": [{**mrn, "value": "MRN-2"}],
            "acknowledged_candidates": [a["id"]],
            "distinct_reason": "registrar unsure",
        },
    )
    merged = merge(api, b, a["id"], reversible=False)
    assert merged.status_code == 200, merged.text
    link = merged.json()
    # Same names: no alias needed. The second number stays as a previous one.
    assert "alias" not in {n["name_type"] for n in link["survivor"]["names"]}
    assert [i["value"] for i in link["survivor"]["identifiers"]] == ["MRN-1"]
    with factory() as s:
        kept = s.scalars(
            select(PatientIdentifier).where(
                PatientIdentifier.tenant_id == api.tenant.tenant_id,
                PatientIdentifier.value == "MRN-2",
                PatientIdentifier.patient_id == uuid.UUID(a["id"]),
            )
        ).one()
        task = s.scalars(
            select(DuplicateCandidate).where(DuplicateCandidate.tenant_id == api.tenant.tenant_id)
        ).one()
    assert (kept.identifier_type, kept.active_marker) == ("previous", None)
    assert (task.resolved, task.resolution) == (True, "merged")
    irreversible = api.post(
        "steward", f"/v1/merge-links/{link['id']}/unmerge", {"reason": "abc"}, **if_match(1)
    )
    assert irreversible.json()["error"]["code"] == "not_reversible"


def test_merge_chains_are_followed(api: Api) -> None:
    def person(n: int) -> dict[str, Any]:
        return create(
            api,
            {
                "family_name": f"Chain{'abcdefgh'[n]}",
                "given_names": "Test",
                "birth_date": f"19{50 + n * 7}-01-0{n + 1}",
                "administrative_sex": "male",
            },
        )

    a, b, c = person(0), person(1), person(2)
    enc = admit(api, a["id"], visit="V-CHAIN")
    first = merge(api, a, b["id"]).json()
    b["version"] += 1
    merge(api, b, c["id"])
    chart = api.get("clinician", f"/v1/patients/{c['id']}/chart").json()
    assert [e["id"] for e in chart["encounters"]] == [enc["id"]]
    assert set(chart["merged_records"]) == {a["id"], b["id"]}
    x = person(3)
    into_merged = merge(api, x, a["id"])
    assert into_merged.json()["error"]["code"] == "survivor_not_mergeable"
    blocked = api.post(
        "steward", f"/v1/merge-links/{first['id']}/unmerge", {"reason": "abc"}, **if_match(1)
    )
    assert blocked.json()["error"]["code"] == "survivor_since_merged"
