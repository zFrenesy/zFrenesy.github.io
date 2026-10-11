"""Ledger events (§4, docs/adr/0006).

An event records one fact with its own provenance: who acted, which entities
it concerns, when it happened (with the precision actually known), when it was
recorded, where that time came from, and the policy in force. Its idempotency
key is derived from the *request* (type, scope and external reference), not
from the outcome, so a repeated or resumed workflow run maps onto the event
already recorded instead of creating a second one.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from rp.canonical import digest
from rp.identity.ids import IdSource, new_id
from rp.timeutil import Clock, DateClaim, format_instant
from rp.validation.records import validate_record

__all__ = ["EventError", "idempotency_key", "logical_content", "make_event"]


class EventError(ValueError):
    pass


def idempotency_key(event_type: str, scope: Mapping[str, Any], external_ref: Any = None) -> str:
    return digest({"version": "I/1", "type": event_type, "scope": dict(scope), "external_ref": external_ref})


def logical_content(event: Mapping[str, Any]) -> dict[str, Any]:
    """The part of an event that must match when the same idempotency key is seen again."""
    return {key: event[key] for key in ("type", "targets", "payload", "idempotency_key")}


def make_event(
    *,
    event_type: str,
    actor: Mapping[str, Any],
    targets: Iterable[str],
    payload: Mapping[str, Any],
    scope: Mapping[str, Any],
    policy_version: str,
    clock: Clock,
    id_source: IdSource | None = None,
    occurred_at: DateClaim | None = None,
    time_source: str = "system_clock",
    external_ref: Any = None,
    evidence: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build and validate an event. ``occurred_at`` defaults to the recording instant."""
    recorded_at = format_instant(clock.now())
    occurred = occurred_at or DateClaim(recorded_at, "instant")
    event = {
        "schema_version": 1,
        "event_id": new_id("event", id_source),
        "type": event_type,
        "actor": dict(actor),
        "targets": list(dict.fromkeys(targets)),
        "occurred_at": occurred.to_json(),
        "recorded_at": recorded_at,
        "time_source": time_source,
        "evidence": [dict(e) for e in evidence],
        "policy_version": policy_version,
        "idempotency_key": idempotency_key(event_type, scope, external_ref),
        "payload": dict(payload),
    }
    errors = [i for i in validate_record("event", event, catalog=None) if i.severity == "error"]
    if errors:
        raise EventError("invalid event: " + "; ".join(str(i) for i in errors))
    return event
