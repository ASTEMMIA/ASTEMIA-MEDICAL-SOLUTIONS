"""Correspondence rules (SA-12, UG04): pure domain."""

import hashlib

import pytest

from astemia.domain import documents as dc
from astemia.domain.common import InvalidTransition, InvariantViolation

PDF = b"%PDF-1.7\n1 0 obj << /Type /Catalog >> endobj\n%%EOF"


def test_digest_is_sha256() -> None:
    assert dc.digest(PDF) == hashlib.sha256(PDF).hexdigest()


@pytest.mark.parametrize(
    ("media_type", "content", "scan", "reason"),
    [
        ("application/pdf", PDF, dc.Scan.CLEAN, None),
        ("image/png", b"\x89PNG\r\n\x1a\n...", dc.Scan.CLEAN, None),
        ("image/jpeg", b"\xff\xd8\xff\xe0...", dc.Scan.CLEAN, None),
        ("image/tiff", b"MM\x00*...", dc.Scan.CLEAN, None),
        ("text/plain", "Dear doctor, ✓".encode(), dc.Scan.CLEAN, None),
        ("image/png", PDF, dc.Scan.UNCLEAN, "content_does_not_match_type"),
        ("text/plain", b"\xff\xfe\x00bad", dc.Scan.UNCLEAN, "not_utf8_text"),
        (
            "application/pdf",
            PDF + b"/OpenAction /JS (app.alert(1))",
            dc.Scan.UNCLEAN,
            "active_content",
        ),
    ],
)
def test_content_checks(media_type: str, content: bytes, scan: dc.Scan, reason: str | None) -> None:
    assert dc.check_content(media_type, content) == (scan, reason)


@pytest.mark.parametrize(
    ("media_type", "content", "code"),
    [
        ("application/x-msdownload", b"MZ", "bad_media_type"),
        ("application/pdf", b"", "empty_file"),
        ("application/pdf", b"%PDF-" + b"0" * dc.MAX_BYTES, "file_too_large"),
    ],
)
def test_refused_outright(media_type: str, content: bytes, code: str) -> None:
    with pytest.raises(InvariantViolation) as e:
        dc.check_content(media_type, content)
    assert e.value.code == code


def test_unclean_files_never_open_and_ambiguous_matches_need_a_decision() -> None:
    dc.check_openable(dc.Scan.CLEAN)
    with pytest.raises(InvalidTransition) as e:
        dc.check_openable(dc.Scan.UNCLEAN)
    assert e.value.code == "document_unclean"
    dc.check_adjudicated(1, None)
    dc.check_adjudicated(2, "Same NIN on the letter head")
    with pytest.raises(InvariantViolation) as e2:
        dc.check_adjudicated(2, None)
    assert e2.value.code == "ambiguous_match"


def test_document_lifecycle() -> None:
    S = dc.DocumentStatus
    assert dc.move(S.QUARANTINED, S.FILED) is S.FILED
    assert dc.move(S.FILED, S.REVIEWED) is S.REVIEWED
    for current, target in ((S.REJECTED, S.FILED), (S.REVIEWED, S.REVIEWED)):
        with pytest.raises(InvalidTransition):
            dc.move(current, target)
