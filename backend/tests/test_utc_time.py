from datetime import UTC, datetime, timedelta, timezone

from app.core.time import UTCDateTime, utc_now


def test_utc_now_returns_an_aware_utc_instant() -> None:
    value = utc_now()

    assert value.tzinfo is UTC
    assert value.utcoffset() == timedelta(0)


def test_utc_datetime_normalizes_writes_and_restores_legacy_utc_values() -> None:
    field = UTCDateTime()
    offset_value = datetime(2026, 8, 3, 9, 0, tzinfo=timezone(timedelta(hours=8)))

    stored = field.process_bind_param(offset_value, None)  # type: ignore[arg-type]
    restored = field.process_result_value(stored, None)  # type: ignore[arg-type]
    legacy = field.process_result_value(datetime(2026, 8, 3, 1, 0), None)  # type: ignore[arg-type]

    assert stored == datetime(2026, 8, 3, 1, 0)
    assert restored == datetime(2026, 8, 3, 1, 0, tzinfo=UTC)
    assert legacy == datetime(2026, 8, 3, 1, 0, tzinfo=UTC)
