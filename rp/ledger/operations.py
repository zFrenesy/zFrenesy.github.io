"""Ledger operations: plan against current state, append with compare-and-swap, retry on conflict.

Each operation is idempotent. A repeated or resumed run either finds its
result already in the derived state (and appends nothing) or appends an
event whose idempotency key matches the one already recorded. Domain
refusals (alias taken, stale predecessor) are raised, never retried away.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from rp.identity.aliases import AliasReservation, plan_abandon, plan_bind
from rp.identity.ids import IdSource
from rp.ledger.events import make_event
from rp.ledger.state import LedgerState, rebuild
from rp.ledger.store import AppendResult, LedgerConflict, LedgerStore
from rp.timeutil import Clock

__all__ = [
    "EventContext",
    "LedgerBusy",
    "StateCache",
    "abandon_alias",
    "accept_revision",
    "append_with_retry",
    "bind_alias",
    "record_events",
    "reserve_alias",
]

DEFAULT_MAX_ATTEMPTS = 200


class LedgerBusy(Exception):
    """Too many consecutive conflicts; the work stays durable-pending and is retried later."""


class StateCache:
    """Incrementally maintained derived state for a single-threaded writer.

    Equivalent to rebuilding from the full log on every attempt, but applies
    only the events appended since the last refresh.
    """

    def __init__(self, store: LedgerStore):
        self._store = store
        self._position = 0
        self.state = LedgerState()

    def refresh(self) -> tuple[str, LedgerState]:
        head, new_events = self._store.read_since(self._position)
        for event in new_events:
            self.state.apply(event)
        self._position += len(new_events)
        return head, self.state


@dataclass(frozen=True)
class EventContext:
    actor: Mapping[str, Any]
    clock: Clock
    policy_version: str
    id_source: IdSource | None = None


def append_with_retry(
    store: LedgerStore,
    build: Callable[[LedgerState], list[dict[str, Any]]],
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    on_conflict: Callable[[], None] | None = None,
    cache: StateCache | None = None,
) -> tuple[LedgerState, AppendResult]:
    """Read, rebuild, plan and append until the append lands on the head it planned against."""
    for _ in range(max_attempts):
        if cache is not None:
            head, state = cache.refresh()
        else:
            head, events = store.read()
            state = rebuild(events)
        planned = build(state)
        if not planned:
            return state, AppendResult(head, (), ())
        try:
            return state, store.append(head, planned)
        except LedgerConflict:
            if on_conflict is not None:
                on_conflict()
    raise LedgerBusy(f"gave up after {max_attempts} conflicting attempts")


def reserve_alias(
    store: LedgerStore,
    plan: Callable[[LedgerState], AliasReservation],
    ctx: EventContext,
    **retry: Any,
) -> AliasReservation:
    """Reserve the alias that ``plan`` chooses against the current state."""
    chosen: list[AliasReservation] = []

    def build(state: LedgerState) -> list[dict[str, Any]]:
        reservation = plan(state)
        chosen[:] = [reservation]
        if reservation.existing:
            return []
        return [
            make_event(
                event_type="alias_reserved",
                actor=ctx.actor,
                targets=[reservation.entity_id],
                payload=reservation.payload(),
                scope={"entity_id": reservation.entity_id, "purpose": "primary_alias"},
                policy_version=ctx.policy_version,
                clock=ctx.clock,
                id_source=ctx.id_source,
            )
        ]

    _, result = append_with_retry(store, build, **retry)
    reservation = chosen[0]
    if result.existing:
        recorded = result.existing[0]["payload"]
        return AliasReservation(**recorded, existing=True)
    return reservation


def _alias_transition(store, event_type, check, alias, entity_id, ctx, extra, **retry) -> bool:
    def build(state: LedgerState) -> list[dict[str, Any]]:
        if not check(state):
            return []
        return [
            make_event(
                event_type=event_type,
                actor=ctx.actor,
                targets=[entity_id],
                payload={"alias": alias, "entity_id": entity_id, **extra},
                scope={"alias": alias, "transition": event_type},
                policy_version=ctx.policy_version,
                clock=ctx.clock,
                id_source=ctx.id_source,
            )
        ]

    _, result = append_with_retry(store, build, **retry)
    return bool(result.appended)


def bind_alias(store: LedgerStore, alias: str, entity_id: str, ctx: EventContext, **retry: Any) -> bool:
    """Make a reserved alias permanent. Returns False if it was already bound."""
    return _alias_transition(
        store, "alias_bound", lambda s: plan_bind(s, alias=alias, entity_id=entity_id), alias, entity_id, ctx, {}, **retry
    )


def abandon_alias(store: LedgerStore, alias: str, entity_id: str, reason: str, ctx: EventContext, **retry: Any) -> bool:
    """Abandon a reserved alias; it stays burned and is never recycled."""
    return _alias_transition(
        store, "alias_abandoned", lambda s: plan_abandon(s, alias=alias), alias, entity_id, ctx, {"reason": reason}, **retry
    )


def accept_revision(
    store: LedgerStore,
    *,
    contribution_id: str,
    revision_id: str,
    expected_predecessor: str | None,
    scientific_fingerprint: str,
    authorization_binding: str,
    ctx: EventContext,
    **retry: Any,
) -> str:
    """Advance a contribution's accepted head and return the sequence label (r1, r2, ...).

    Raises ``StalePredecessor`` when another revision already advanced the head:
    two revisions sharing an expected predecessor can never both be accepted.
    """
    label: list[str] = []

    def build(state: LedgerState) -> list[dict[str, Any]]:
        if revision_id in state.revision_labels:
            label[:] = [state.revision_labels[revision_id]]
            return []
        next_label = state.next_revision_label(contribution_id, expected_predecessor)
        label[:] = [next_label]
        return [
            make_event(
                event_type="revision_accepted",
                actor=ctx.actor,
                targets=[contribution_id, revision_id],
                payload={
                    "contribution_id": contribution_id,
                    "revision_id": revision_id,
                    "predecessor": expected_predecessor,
                    "sequence_label": next_label,
                    "scientific_fingerprint": scientific_fingerprint,
                    "authorization_binding": authorization_binding,
                },
                scope={"contribution_id": contribution_id, "revision_id": revision_id},
                policy_version=ctx.policy_version,
                clock=ctx.clock,
                id_source=ctx.id_source,
            )
        ]

    append_with_retry(store, build, **retry)
    return label[0]


def record_events(store: LedgerStore, events: list[dict[str, Any]], **retry: Any) -> AppendResult:
    """Append fully formed events (their idempotency keys make retries safe)."""
    _, result = append_with_retry(store, lambda state: events, **retry)
    return result
