"""Identity review on top of the patient index (UG02, WF01 steps 1 and 4, CEDA
E3, HS02): explained near-match search, steward review tasks, aliases kept on
merge, and access and orders that follow a merge."""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import AuditEvent, DuplicateCandidate, PatientIdentifier
from tests.conftest import Api
from tests.e2e.test_api03_vertical_slice import admit, order, register
from tests.fixtures.synthetic import ADDRESS

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
    r = api.post("registrar", "/v1/patients", {"address": ADDRESS, **body})
    assert r.status_code == 201, r.text
    return r.json()


def merge(api: Api, prior: dict[str, Any], survivor: dict[str, Any]) -> Any:
    return api.post(
        "steward",
        f"/v1/patients/{prior['id']}/merge",
        {"survivor_id": survivor["id"], "reason": "same person, confirmed at the desk"},
        **if_match(prior["version"]),
    )


# -- WF01 step 1: explained search before registering ------------------------------


def test_match_explains_masks_and_audits(api: Api, factory: sessionmaker[Session]) -> None:
    pid = register(api)
    probe = {**PERSON, "family_name": "Adeyemmi", "mother_name": None}
    r = api.post("registrar", "/v1/patient-index/match", probe)
    assert r.status_code == 200, r.text
    [c] = r.json()["candidates"]
    assert (c["id"], c["band"], c["score"]) == (pid, "possible", 70)
    assert c["reasons"] == [
        "birth_date",
        "family_name_sounds_like",
        "given_name",
        "administrative_sex",
    ]
    assert (c["family_name"], c["given_initial"], c["birth_year"]) == ("Adeyemi", "F", 1984)
    assert "given_names" not in c and "birth_date" not in c  # enough to tell people apart
    assert c["identifiers"][0]["value"] == "*******8901"  # masked for the registrar
    steward = api.post("steward", "/v1/patient-index/match", probe).json()["candidates"][0]
    assert steward["identifiers"][0]["value"] == "12345678901"
    by_number = api.post(
        "registrar",
        "/v1/patient-index/match",
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
        "/v1/patient-index/match",
        {**probe, "family_name": "Nwosu", "given_names": "Ike", "birth_date": "1950-05-05"},
    )
    assert nobody.json() == {"candidates": []}
    with factory() as s:
        searches = s.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.tenant_id == api.tenant.tenant_id,
                AuditEvent.action == "patient_index.match",
            )
        )
    assert searches == 4
    assert api.post("nurse", "/v1/patient-index/match", probe).status_code == 403
    bad = api.post(
        "registrar",
        "/v1/patient-index/match",
        {**probe, "identifiers": [{"issuer": "NG-NIN", "value": "123"}]},
    )
    assert (bad.status_code, bad.json()["error"]["code"]) == (422, "bad_identifier")


# -- WF01: review tasks, opened at registration, resolved by a steward ---------------


def test_registration_opens_reviews_that_a_steward_resolves(api: Api) -> None:
    first = create(api, PERSON)
    assert first["identity_review_tasks"] == []
    near = create(api, {**PERSON, "family_name": "Adeyemmi", "mother_name": None})
    assert near["possible_duplicates"] == []  # not the same family name...
    [task_id] = near["identity_review_tasks"]  # ...but close enough for a steward to look
    [task] = api.get("steward", "/v1/identity-review-tasks").json()
    assert task["id"] == task_id
    assert (task["origin"], task["score"], task["resolved"]) == ("registration", 70, False)
    assert {r["id"] for r in task["records"]} == {first["id"], near["id"]}
    assert api.get("registrar", "/v1/identity-review-tasks").status_code == 403

    path = f"/v1/identity-review-tasks/{task_id}/resolve"
    body = {"resolution": "distinct", "reason": "different mothers, documents checked"}
    assert api.post("steward", path, body).status_code == 428
    assert api.post("registrar", path, body, **if_match(1)).status_code == 403
    done = api.post("steward", path, body, **if_match(1))
    assert done.status_code == 200, done.text
    out = done.json()
    assert (out["resolution"], out["note"], out["version"]) == ("distinct", body["reason"], 2)
    assert out["resolved_by_id"] == str(api.tenant.practitioners["steward"])
    assert done.headers["ETag"] == '"2"'
    assert api.post("steward", path, body, **if_match(1)).json()["error"]["code"] == (
        "stale_version"
    )
    assert api.post("steward", path, body, **if_match(2)).json()["error"]["code"] == (
        "review_already_resolved"
    )
    assert api.get("steward", "/v1/identity-review-tasks").json() == []
    closed = api.get("steward", "/v1/identity-review-tasks?resolved=true").json()
    assert [t["id"] for t in closed] == [task_id]


def test_a_merge_answers_the_pairs_review(api: Api, factory: sessionmaker[Session]) -> None:
    a = create(api, PERSON)
    b = create(api, PERSON)  # alerted, never blocked (ICRS 3.2.8)
    assert b["possible_duplicates"] == [a["id"]] and len(b["identity_review_tasks"]) == 1
    merged = merge(api, b, a)
    assert merged.status_code == 200, merged.text
    # The same name needs no alias.
    assert [n["name_type"] for n in merged.json()["survivor"]["names"]] == ["usual"]
    with factory() as s:
        task = s.scalars(
            select(DuplicateCandidate).where(DuplicateCandidate.tenant_id == api.tenant.tenant_id)
        ).one()
    assert (task.resolved, task.resolution) == (True, "merged")
    assert task.resolved_by_id == api.tenant.practitioners["steward"]


# -- HS02 / E3: an unidentified arrival matched to a registered patient -------------


def test_unidentified_arrival_merged_and_unmerged(api: Api, factory: sessionmaker[Session]) -> None:
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

    merged = merge(api, arrival, known)
    assert merged.status_code == 200, merged.text
    survivor = merged.json()["survivor"]
    assert {(i["issuer"], i["value"], i["identifier_type"]) for i in survivor["identifiers"]} == {
        ("NG-NIN", "12345678901", "current"),
        ("LOCAL-MRN", "ER-0001", "temporary"),
    }
    assert ("alias", "Unknown", "Female") in {
        (n["name_type"], n["family_name"], n["given_name"]) for n in survivor["names"]
    }
    with factory() as s:
        copies = s.scalars(
            select(PatientIdentifier).where(
                PatientIdentifier.tenant_id == api.tenant.tenant_id,
                PatientIdentifier.value == "ER-0001",
            )
        ).all()
    assert len(copies) == 2 and len({c.author_id for c in copies}) == 1  # original author kept
    assert {c.author_id for c in copies} == {api.tenant.practitioners["registrar"]}

    # Access and orders follow the merge.
    chart = api.get("clinician", f"/v1/patients/{known['id']}/chart")
    assert chart.status_code == 200, chart.text
    assert [e["id"] for e in chart.json()["encounters"]] == [enc["id"]]
    o = order(api, known["id"], enc["id"])
    assert o["patient_id"] == arrival["id"]  # the order stays with its encounter's record
    elsewhere = api.post(
        "clinician",
        "/v1/orders",
        {
            "patient_id": known["id"],
            "encounter_id": admit(api, register(api, "99999999999"), visit="V-OTHER")["id"],
            "code_system": "http://loinc.org",
            "code": "2823-3",
            "display": "Potassium",
        },
    )
    assert elsewhere.json()["error"]["code"] == "encounter_patient_mismatch"
    found = api.post(
        "steward",
        "/v1/patient-index/match",
        {**PERSON, "family_name": "Unknown", "given_names": "Female", "mother_name": None},
    ).json()["candidates"]
    assert found[0]["id"] == known["id"] and "family_name" in found[0]["reasons"]  # by alias

    link = merged.json()["merge_link_id"]
    undone = api.post("steward", f"/v1/merge-links/{link}/unmerge", {"reason": "wristband misread"})
    assert undone.status_code == 200, undone.text
    assert "alias" not in {n["name_type"] for n in undone.json()["survivor"]["names"]}
    assert undone.json()["prior"]["status"] == "temporary"
    back = api.get("clinician", f"/v1/patients/{arrival['id']}/chart").json()
    assert [x["id"] for x in back["orders"]] == [o["id"]]
    assert api.get("clinician", f"/v1/patients/{known['id']}/chart").status_code == 404
