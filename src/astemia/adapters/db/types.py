"""Column types fixed by CEDA 3.1: BINARY(16) UUIDs and UTC DATETIME(6)."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import BINARY, Dialect
from sqlalchemy.dialects.mysql import DATETIME
from sqlalchemy.types import TypeDecorator


class BinaryUUID(TypeDecorator[uuid.UUID]):
    """Opaque identifier stored as BINARY(16). Never a national identifier."""

    impl = BINARY(16)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> bytes | None:
        if value is None:
            return None
        uid = value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        return uid.bytes

    def process_result_value(self, value: Any, dialect: Dialect) -> uuid.UUID | None:
        if value is None:
            return None
        return uuid.UUID(bytes=bytes(value))


class UTCDateTime(TypeDecorator[datetime]):
    """DATETIME(6) holding UTC. Naive datetimes are rejected on write."""

    impl = DATETIME(fsp=6)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("UTCDateTime requires a timezone-aware datetime")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        assert isinstance(value, datetime)
        return value.replace(tzinfo=UTC)
