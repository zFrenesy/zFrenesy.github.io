from datetime import UTC, datetime, timedelta, timezone

import pytest

from rp.timeutil import (
    DateClaim,
    FixedClock,
    TimeFormatError,
    format_instant,
    is_calendar_date,
    is_instant,
    parse_instant,
)


def test_format_instant_converts_to_utc_and_truncates():
    moment = datetime(2026, 10, 11, 15, 30, 45, 999999, tzinfo=timezone(timedelta(hours=2)))
    assert format_instant(moment) == "2026-10-11T13:30:45Z"


def test_naive_datetimes_are_rejected():
    with pytest.raises(TimeFormatError):
        format_instant(datetime(2026, 1, 1))


@pytest.mark.parametrize(
    "text",
    ["2026-10-11T13:30:45Z", "2024-02-29T00:00:00Z"],
)
def test_valid_instants(text):
    assert is_instant(text)
    assert format_instant(parse_instant(text)) == text


@pytest.mark.parametrize(
    "text",
    [
        "2026-10-11T13:30:45+00:00",
        "2026-10-11T13:30:45.123Z",
        "2026-10-11 13:30:45Z",
        "2026-02-30T00:00:00Z",
        "2026-10-11",
        20261011,
    ],
)
def test_invalid_instants(text):
    assert not is_instant(text)


def test_calendar_dates():
    assert is_calendar_date("2024-02-29")
    assert not is_calendar_date("2026-02-29")
    assert not is_calendar_date("20261011")


@pytest.mark.parametrize(
    "value, precision",
    [("2026", "year"), ("2026-10", "month"), ("2026-10-09", "day"), ("2026-10-09T08:00:00Z", "instant")],
)
def test_date_claims_keep_precision(value, precision):
    claim = DateClaim(value, precision)
    assert DateClaim.from_json(claim.to_json()) == claim


@pytest.mark.parametrize(
    "value, precision",
    [
        ("2026-10-09", "instant"),
        ("2026-10-09T08:00:00Z", "day"),
        ("2026-13", "month"),
        ("0000", "year"),
        ("2026-10-09", "week"),
    ],
)
def test_date_claims_reject_mismatched_precision(value, precision):
    with pytest.raises(TimeFormatError):
        DateClaim(value, precision)


def test_from_json_rejects_extra_fields():
    with pytest.raises(TimeFormatError):
        DateClaim.from_json({"value": "2026", "precision": "year", "time": "00:00"})


def test_fixed_clock_is_deterministic():
    clock = FixedClock("2026-10-01T00:00:00Z", step_seconds=60)
    assert [format_instant(clock.now()) for _ in range(3)] == [
        "2026-10-01T00:00:00Z",
        "2026-10-01T00:01:00Z",
        "2026-10-01T00:02:00Z",
    ]
    assert clock.now().tzinfo is UTC
