"""UTC instants, injectable clocks, and date claims with explicit precision.

System timestamps are UTC instants written ``YYYY-MM-DDTHH:MM:SSZ``. Claimed
dates (a legacy ``FIRST_POSTED`` header, a model generation date) keep the
precision they were given: a date-only claim never gains a time of day.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

__all__ = [
    "PRECISIONS",
    "Clock",
    "DateClaim",
    "FixedClock",
    "SystemClock",
    "TimeFormatError",
    "format_instant",
    "is_calendar_date",
    "is_instant",
    "parse_instant",
]

PRECISIONS = ("year", "month", "day", "instant")
_INSTANT = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})Z")
_DAY = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_MONTH = re.compile(r"([0-9]{4})-(0[1-9]|1[0-2])")
_YEAR = re.compile(r"[0-9]{4}")


class TimeFormatError(ValueError):
    pass


def format_instant(moment: datetime) -> str:
    """Format an aware datetime as a UTC instant, truncating sub-second digits."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise TimeFormatError("naive datetimes are not allowed; use an aware UTC datetime")
    m = moment.astimezone(UTC)
    return f"{m.year:04d}-{m.month:02d}-{m.day:02d}T{m.hour:02d}:{m.minute:02d}:{m.second:02d}Z"


def parse_instant(text: str) -> datetime:
    match = _INSTANT.fullmatch(text) if isinstance(text, str) else None
    if not match:
        raise TimeFormatError(f"{text!r} is not a UTC instant (YYYY-MM-DDTHH:MM:SSZ)")
    try:
        return datetime(*(int(g) for g in match.groups()), tzinfo=UTC)
    except ValueError as exc:
        raise TimeFormatError(f"{text!r} is not a valid instant: {exc}") from exc


def is_instant(text: object) -> bool:
    try:
        parse_instant(text)  # type: ignore[arg-type]
    except TimeFormatError:
        return False
    return True


def is_calendar_date(text: object) -> bool:
    match = _DAY.fullmatch(text) if isinstance(text, str) else None
    if not match:
        return False
    try:
        date(*(int(g) for g in match.groups()))
    except ValueError:
        return False
    return True


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """Deterministic clock: returns ``start``, then advances by ``step`` on each call."""

    def __init__(self, start: str | datetime, step_seconds: int = 1):
        self._next = parse_instant(start) if isinstance(start, str) else start.astimezone(UTC)
        self._step = timedelta(seconds=step_seconds)
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            current = self._next
            self._next = current + self._step
            return current


@dataclass(frozen=True, slots=True)
class DateClaim:
    """A date as claimed or observed, with the precision it actually has."""

    value: str
    precision: str

    def __post_init__(self) -> None:
        if self.precision not in PRECISIONS:
            raise TimeFormatError(f"unknown precision {self.precision!r}")
        valid = {
            "year": lambda v: bool(_YEAR.fullmatch(v)) and v != "0000",
            "month": lambda v: bool(_MONTH.fullmatch(v)) and not v.startswith("0000"),
            "day": is_calendar_date,
            "instant": is_instant,
        }[self.precision]
        if not isinstance(self.value, str) or not valid(self.value):
            raise TimeFormatError(f"{self.value!r} does not match precision {self.precision!r}")

    @classmethod
    def at(cls, moment: datetime) -> DateClaim:
        return cls(format_instant(moment), "instant")

    def to_json(self) -> dict[str, str]:
        return {"value": self.value, "precision": self.precision}

    @classmethod
    def from_json(cls, data: Any) -> DateClaim:
        if not isinstance(data, dict) or set(data) != {"value", "precision"}:
            raise TimeFormatError("a date claim is an object with exactly 'value' and 'precision'")
        return cls(data["value"], data["precision"])
