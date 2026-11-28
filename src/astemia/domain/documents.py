"""Clinical correspondence (CEDA SA-12 Document and DocumentVersion; UG04).
Pure rules.

A document arrives quarantined. Its bytes are checked and fixed by their
SHA-256 digest; it is published to the chart only when its patient link is
accepted, and an unclean file is never opened or sent for review. Correcting
the indexing makes a new version that keeps the original digest.
"""

import hashlib
from enum import StrEnum

from astemia.domain.common import InvalidTransition, InvariantViolation, transition

MAX_BYTES = 10 * 1024 * 1024

# Accepted file types, with the bytes each must start with.
SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "application/pdf": (b"%PDF-",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/tiff": (b"II*\x00", b"MM\x00*"),
    "text/plain": (),
}

# Active content a clinical letter has no business carrying.
PDF_ACTIVE = (b"/JavaScript", b"/JS", b"/Launch", b"/EmbeddedFile", b"/OpenAction")


class DocumentStatus(StrEnum):
    QUARANTINED = "quarantined"
    REJECTED = "rejected"  # failed the content checks; kept, never opened
    FILED = "filed"
    REVIEWED = "reviewed"


_DOCUMENT: dict[DocumentStatus, frozenset[DocumentStatus]] = {
    DocumentStatus.QUARANTINED: frozenset({DocumentStatus.FILED}),
    DocumentStatus.FILED: frozenset({DocumentStatus.REVIEWED}),
}


def move(current: DocumentStatus, target: DocumentStatus) -> DocumentStatus:
    return transition(current, target, _DOCUMENT, "document")


class Scan(StrEnum):
    CLEAN = "clean"
    UNCLEAN = "unclean"


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def check_content(media_type: str, content: bytes) -> tuple[Scan, str | None]:
    """Structural checks done here. A file that fails is kept (its digest
    proves what was received) but rejected; it is never opened or routed."""
    if media_type not in SIGNATURES:
        raise InvariantViolation(f"{media_type} files are not accepted", code="bad_media_type")
    if not content:
        raise InvariantViolation("the file is empty", code="empty_file")
    if len(content) > MAX_BYTES:
        raise InvariantViolation("the file is larger than 10 MB", code="file_too_large")
    signatures = SIGNATURES[media_type]
    if signatures and not content.startswith(signatures):
        return Scan.UNCLEAN, "content_does_not_match_type"
    if media_type == "text/plain":
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            return Scan.UNCLEAN, "not_utf8_text"
    if media_type == "application/pdf" and any(a in content for a in PDF_ACTIVE):
        return Scan.UNCLEAN, "active_content"
    return Scan.CLEAN, None


def check_openable(scan: Scan) -> None:
    if scan is Scan.UNCLEAN:
        raise InvalidTransition(
            "this file failed its content checks and cannot be opened or routed",
            code="document_unclean",
        )


def check_adjudicated(candidates: int, adjudication: str | None) -> None:
    """UG04: an ambiguous match stays quarantined until someone decides."""
    if candidates > 1 and not adjudication:
        raise InvariantViolation(
            "more than one patient could match; record why this one is right",
            code="ambiguous_match",
        )
