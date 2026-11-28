"""Clinical correspondence (CEDA SA-12; UG04).

UG04 acceptance: an ambiguous match remains in quarantine; after adjudication
the intended reviewer receives one task; later corrections preserve the
original digest; an unclean or corrupted file cannot be opened from the chart
or sent to a reviewer."""

import base64
import hashlib
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from astemia.adapters.db.models import DocumentObject
from tests.conftest import Api
from tests.e2e.test_api03_vertical_slice import admit, register

LETTER = b"%PDF-1.7\n1 0 obj << /Type /Catalog >> endobj\n% Clinic letter\n%%EOF"
HINT = {
    "family_name": "Adeyemi",
    "given_names": "Folake",
    "birth_date": "1984-03-09",
    "administrative_sex": "female",
}


def if_match(version: int) -> dict[str, str]:
    return {"If-Match": f'"{version}"'}


def code(r: Any) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


def receive(
    api: Api, content: bytes = LETTER, media_type: str = "application/pdf", **extra: Any
) -> Any:
    body = {
        "sender": "Lagos Teaching Hospital cardiology clinic",
        "received_at": datetime.now(UTC).isoformat(),
        "document_type": "letter",
        "title": "Clinic letter",
        "media_type": media_type,
        "content_base64": base64.b64encode(content).decode(),
        **extra,
    }
    return api.post("clerk", "/v1/documents", body)


def file(
    api: Api, doc: dict[str, Any], patient_id: str, reviewer: str = "clinician", **extra: Any
) -> Any:
    return api.post(
        "clerk",
        f"/v1/documents/{doc['id']}/file",
        {"patient_id": patient_id, "reviewer_id": str(api.tenant.practitioners[reviewer]), **extra},
        **if_match(doc["version"]),
    )


def test_a_letter_is_quarantined_filed_reviewed_and_keeps_its_bytes(
    api: Api, factory: sessionmaker[Session]
) -> None:
    pid = register(api)
    admit(api, pid)
    got = receive(api, patient_hint={**HINT, "nin": "123 456 789 01"})
    assert got.status_code == 201, got.text
    doc = got.json()
    assert (doc["status"], doc["scan"], doc["digest"]) == (
        "quarantined",
        "clean",
        hashlib.sha256(LETTER).hexdigest(),
    )
    [candidate] = doc["candidates"]
    assert (candidate["id"], candidate["score"]) == (pid, 100)
    assert candidate["identifiers"][0]["value"] == "*******8901"  # masked for the clerk

    # Quarantined: not on the chart, not openable by the care team.
    assert api.get("clinician", f"/v1/patients/{pid}/chart").json()["documents"] == []
    assert api.get("clinician", f"/v1/documents/{doc['id']}").status_code == 404
    clerk_copy = api.get("clerk", f"/v1/documents/{doc['id']}/content")
    assert clerk_copy.content == LETTER
    assert clerk_copy.headers["X-Content-Type-Options"] == "nosniff"
    assert [d["id"] for d in api.get("clerk", "/v1/documents").json()] == [doc["id"]]
    assert api.get("clinician", "/v1/documents").status_code == 403

    assert code(
        api.post(
            "clerk",
            f"/v1/documents/{doc['id']}/file",
            {"patient_id": pid, "reviewer_id": str(api.tenant.practitioners["clinician"])},
        )
    ) == (428, "precondition_required")
    filed = file(api, doc, pid)
    assert filed.status_code == 200, filed.text
    assert (filed.json()["status"], filed.json()["reviewer_id"]) == (
        "filed",
        str(api.tenant.practitioners["clinician"]),
    )
    [shown] = api.get("clinician", f"/v1/patients/{pid}/chart").json()["documents"]
    assert (shown["id"], shown["reviewed"]) == (doc["id"], False)
    assert api.get("clinician", f"/v1/documents/{doc['id']}/content").content == LETTER
    read = api.get("clinician", f"/v1/documents/{doc['id']}")
    assert read.status_code == 200 and read.json()["candidates"] == []  # filed: no candidates
    assert [v["reason"] for v in read.json()["versions"]] == ["received", "filed"]
    assert api.get("clinician2", f"/v1/documents/{doc['id']}").status_code == 404

    review = f"/v1/documents/{doc['id']}/review"
    assert api.post("clinician2", review, {"note": "Seen"}, **if_match(2)).status_code == 404
    done = api.post("clinician", review, {"note": "Seen; follow up in clinic"}, **if_match(2))
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "reviewed"
    assert code(api.post("clinician", review, {"note": "again"}, **if_match(3))) == (
        422,
        "invalid_transition",
    )
    # The same bytes received again are stored once.
    again = receive(api)
    assert again.json()["digest"] == doc["digest"]
    with factory() as s:
        stored = s.scalar(
            select(func.count())
            .select_from(DocumentObject)
            .where(DocumentObject.tenant_id == api.tenant.tenant_id)
        )
    assert stored == 1


def test_an_ambiguous_match_stays_quarantined_until_adjudicated(api: Api) -> None:
    first = register(api, "11111111111")
    second = register(api, "22222222222")  # the same name and birthday
    doc = receive(api, patient_hint=HINT).json()
    assert {c["id"] for c in doc["candidates"]} == {first, second}
    assert code(file(api, doc, first)) == (422, "ambiguous_match")
    decided = file(api, doc, first, adjudication="Address and NIN on the letter match")
    assert decided.status_code == 200, decided.text
    assert decided.json()["adjudication"] == "Address and NIN on the letter match"
    # One reviewer, and only that reviewer, can sign it off.
    admit(api, first)
    by_reviewer = api.post(
        "clinician",
        f"/v1/documents/{doc['id']}/review",
        {"note": "Seen"},
        **if_match(2),
    )
    assert by_reviewer.status_code == 200  # the named reviewer
    other = receive(api, content=LETTER + b" ")
    routed = file(api, other.json(), first, reviewer="clinician2")
    assert code(
        api.post(
            "clinician", f"/v1/documents/{other.json()['id']}/review", {"note": "x1"}, **if_match(2)
        )
    ) == (403, "not_reviewer")
    assert routed.status_code == 200


def test_unclean_files_are_kept_but_never_opened_or_routed(api: Api) -> None:
    pid = register(api)
    active = receive(api, content=LETTER + b"/OpenAction << /S /JavaScript >>")
    assert active.status_code == 201
    bad = active.json()
    assert (bad["status"], bad["scan"], bad["scan_reason"]) == (
        "rejected",
        "unclean",
        "active_content",
    )
    assert code(file(api, bad, pid)) == (422, "document_unclean")
    assert code(api.get("clerk", f"/v1/documents/{bad['id']}/content")) == (422, "document_unclean")
    assert [d["id"] for d in api.get("clerk", "/v1/documents?status=rejected").json()] == [
        bad["id"]
    ]
    disguised = receive(api, media_type="image/png").json()
    assert disguised["scan_reason"] == "content_does_not_match_type"

    assert code(receive(api, media_type="application/x-msdownload")) == (422, "bad_media_type")
    assert code(receive(api, content_base64="not base64!")) == (422, "bad_content")
    assert code(receive(api, content=b"")) == (422, "empty_file")
    assert code(receive(api, patient_hint={**HINT, "nin": "123"})) == (422, "bad_identifier")
    assert api.get("clerk", "/v1/documents/01a21e00-0000-7000-8000-000000000000").status_code == 404


def test_a_misfiled_letter_is_reindexed_and_keeps_its_digest(api: Api) -> None:
    right = register(api, "33333333333")
    wrong = api.post(
        "registrar",
        "/v1/patients",
        {
            **HINT,
            "family_name": "Okafor",
            "given_names": "Chidi",
            "administrative_sex": "male",
            "birth_date": "1970-01-01",
        },
    ).json()["id"]
    enc = admit(api, right)
    doc = receive(api).json()
    filed = file(api, doc, wrong).json()
    assert code(
        api.post(
            "clerk",
            f"/v1/documents/{doc['id']}/reindex",
            {
                "patient_id": right,
                "encounter_id": admit(api, wrong, visit="V-W")["id"],
                "document_type": "letter",
                "reason": "Wrong patient",
            },
            **if_match(2),
        )
    ) == (422, "encounter_patient_mismatch")
    fixed = api.post(
        "clerk",
        f"/v1/documents/{doc['id']}/reindex",
        {
            "patient_id": right,
            "encounter_id": enc["id"],
            "title": "Cardiology letter",
            "document_type": "letter",
            "reason": "Filed to the wrong patient",
        },
        **if_match(filed["version"]),
    )
    assert fixed.status_code == 200, fixed.text
    out = fixed.json()
    assert out["patient_id"] == right and out["status"] == "filed"
    assert [(v["version_number"], v["reason"]) for v in out["versions"]] == [
        (1, "received"),
        (2, "filed"),
        (3, "Filed to the wrong patient"),
    ]
    assert {v["digest"] for v in out["versions"]} == {doc["digest"]}  # the original, always
    assert [
        d["id"] for d in api.get("clinician", f"/v1/patients/{right}/chart").json()["documents"]
    ] == [doc["id"]]
    quarantined = receive(api, content=LETTER + b"\n").json()
    assert code(
        api.post(
            "clerk",
            f"/v1/documents/{quarantined['id']}/reindex",
            {"patient_id": right, "document_type": "letter", "reason": "x" * 3},
            **if_match(1),
        )
    ) == (409, "not_filed")
    # A merged record is never filed to; the survivor is.
    merged = api.post(
        "steward",
        f"/v1/patients/{wrong}/merge",
        {"survivor_id": right, "reason": "Same person, confirmed"},
        **if_match(1),
    )
    assert merged.status_code == 200, merged.text
    assert code(file(api, quarantined, wrong)) == (409, "patient_merged")
