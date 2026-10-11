"""Append-only ledger stores with compare-and-swap appends.

The head is a hash chain over canonical event encodings, so it identifies the
exact history. ``append`` succeeds only if the caller's expected head is still
current, which is the in-memory equivalent of the non-force conditional ref
update the Git-backed store (milestone 5) will use. Concurrent writers that
lose the race re-read, re-plan and retry; nothing is overwritten.
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from rp.canonical import canonical_json, digest
from rp.ledger.events import EventError, logical_content
from rp.validation.records import validate_record

__all__ = [
    "GENESIS",
    "AppendResult",
    "IdempotencyConflict",
    "LedgerConflict",
    "LedgerStore",
    "MemoryLedger",
]

GENESIS = digest({"version": "L/1", "genesis": True})


class LedgerConflict(Exception):
    """The ledger moved since the caller read it. Re-read, re-plan and retry."""

    def __init__(self, expected: str, actual: str):
        self.expected = expected
        self.actual = actual
        super().__init__(f"ledger head is {actual}, not {expected}")


class IdempotencyConflict(Exception):
    """The same idempotency key was used for a different logical event."""


@dataclass(frozen=True)
class AppendResult:
    head: str
    appended: tuple[dict[str, Any], ...]
    existing: tuple[dict[str, Any], ...]


class LedgerStore(Protocol):
    def read(self) -> tuple[str, list[dict[str, Any]]]:
        """Return the head and all events, atomically."""
        ...

    def append(self, expected_head: str, events: Sequence[dict[str, Any]]) -> AppendResult: ...


def next_head(head: str, event: dict[str, Any]) -> str:
    return digest({"previous": head, "event": event})


class MemoryLedger:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: list[dict[str, Any]] = []
        self._by_key: dict[str, dict[str, Any]] = {}
        self._ids: set[str] = set()
        self._head = GENESIS

    def read(self) -> tuple[str, list[dict[str, Any]]]:
        with self._lock:
            return self._head, copy.deepcopy(self._events)

    def append(self, expected_head: str, events: Sequence[dict[str, Any]]) -> AppendResult:
        with self._lock:
            fresh: list[dict[str, Any]] = []
            existing: list[dict[str, Any]] = []
            mismatched: list[str] = []
            keys: set[str] = set()
            for event in events:
                errors = [i for i in validate_record("event", event, catalog=None) if i.severity == "error"]
                if errors:
                    raise EventError("refusing invalid event: " + "; ".join(str(i) for i in errors))
                key = event["idempotency_key"]
                if key in keys:
                    raise IdempotencyConflict(f"idempotency key {key} appears twice in one append")
                keys.add(key)
                prior = self._by_key.get(key)
                if prior is None:
                    if event["event_id"] in self._ids:
                        raise IdempotencyConflict(f"event id {event['event_id']} is already recorded")
                    fresh.append(event)
                elif logical_content(prior) != logical_content(event):
                    mismatched.append(key)
                else:
                    existing.append(copy.deepcopy(prior))
            if mismatched:
                # Planned against an older state: re-plan. Planned against this state: a real conflict.
                if expected_head != self._head:
                    raise LedgerConflict(expected_head, self._head)
                raise IdempotencyConflict(f"idempotency key {mismatched[0]} was recorded for a different event")
            if not fresh:
                return AppendResult(self._head, (), tuple(existing))
            if expected_head != self._head:
                raise LedgerConflict(expected_head, self._head)
            for event in fresh:
                stored = copy.deepcopy(event)
                self._head = next_head(self._head, stored)
                self._events.append(stored)
                self._by_key[stored["idempotency_key"]] = stored
                self._ids.add(stored["event_id"])
            return AppendResult(self._head, tuple(copy.deepcopy(fresh)), tuple(existing))

    def export_jsonl(self) -> bytes:
        """Canonical JSON lines, one event per line, in ledger order."""
        _, events = self.read()
        return b"".join(canonical_json(e) + b"\n" for e in events)

    @classmethod
    def from_events(cls, events: Iterable[dict[str, Any]]) -> MemoryLedger:
        ledger = cls()
        for event in events:
            ledger.append(ledger.read()[0], [event])
        return ledger
