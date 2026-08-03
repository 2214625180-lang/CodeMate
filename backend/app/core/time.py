"""Timezone-aware UTC primitives for application and database boundaries."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.types import TypeDecorator


def utc_now() -> datetime:
    """Return the current instant as a timezone-aware UTC datetime."""

    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Persist UTC instants compatibly while always exposing aware datetimes.

    Existing SQLite and PostgreSQL deployments created timestamp-without-time-zone
    columns. Values in those columns have always represented UTC, so the type stores
    normalized naive UTC for backward compatibility and restores ``UTC`` on reads.
    This keeps old data comparable with new values while avoiding a risky rewrite of
    every historical timestamp during a security-maintenance release.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        del dialect
        if value is None:
            return None
        if value.tzinfo is None:
            # Legacy callers are interpreted as UTC at the persistence boundary.
            return value
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        del dialect
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
