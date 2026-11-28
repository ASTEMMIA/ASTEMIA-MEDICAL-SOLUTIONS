"""PACS viewer access (CEDA HS07, WF05; UAT WF05).

The viewer opens a study only with a token we sign: it names the tenant, the
patient, the one study and the practitioner, and expires within minutes. The
PACS checks it against the study it is asked to show, so a token for one
patient's study cannot open another's.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlencode

import jwt

from astemia.config import Settings

AUDIENCE = "astemia-pacs"


@dataclass(frozen=True, slots=True)
class ViewerClaims:
    tenant_id: uuid.UUID
    patient_id: uuid.UUID
    practitioner_id: uuid.UUID
    study_instance_uid: str


class ViewerTokenError(Exception):
    """The token is not ours, has expired, or is for another study."""


class ViewerTokens:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def issue(self, claims: ViewerClaims, now: datetime) -> tuple[str, str, datetime]:
        """(token, viewer URL, expiry)."""
        expires = now + timedelta(seconds=self.settings.pacs_token_seconds)
        token = jwt.encode(
            {
                "aud": AUDIENCE,
                "iat": int(now.timestamp()),
                "exp": int(expires.timestamp()),
                "tid": str(claims.tenant_id),
                "pid": str(claims.patient_id),
                "sub": str(claims.practitioner_id),
                "study": claims.study_instance_uid,
            },
            self.settings.pacs_token_key.get_secret_value(),
            algorithm="HS256",
        )
        query = urlencode({"study": claims.study_instance_uid, "token": token})
        return token, f"{self.settings.pacs_viewer_url}?{query}", expires

    def check(self, token: str, study_instance_uid: str) -> ViewerClaims:
        try:
            raw = jwt.decode(
                token,
                self.settings.pacs_token_key.get_secret_value(),
                algorithms=["HS256"],
                audience=AUDIENCE,
                options={"require": ["exp", "aud", "tid", "pid", "sub", "study"]},
            )
        except jwt.PyJWTError as exc:
            raise ViewerTokenError(str(exc)) from None
        if raw["study"] != study_instance_uid:
            raise ViewerTokenError("this token is for another study")
        return ViewerClaims(
            tenant_id=uuid.UUID(raw["tid"]),
            patient_id=uuid.UUID(raw["pid"]),
            practitioner_id=uuid.UUID(raw["sub"]),
            study_instance_uid=raw["study"],
        )
