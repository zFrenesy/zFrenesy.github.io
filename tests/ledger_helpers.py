"""Shared helpers for ledger tests."""

from rp.catalog import default_catalog
from rp.identity.aliases import plan_external_alias
from rp.identity.ids import SeededIdSource, new_id
from rp.ledger.operations import EventContext, bind_alias, reserve_alias
from rp.ledger.store import MemoryLedger
from rp.timeutil import FixedClock

POLICY = default_catalog().alias_policy
ACTOR = {"kind": "app", "app_slug": "we-solve-publisher"}


def context(seed: str) -> EventContext:
    return EventContext(ACTOR, FixedClock("2026-10-11T00:00:00Z"), "policy/1", SeededIdSource(seed))


def ledger_with_bound_problem(seed: str = "base", number: str = "5") -> tuple[MemoryLedger, str, str]:
    """A ledger holding a bound catalogued problem alias such as ERDOS-5."""
    store = MemoryLedger()
    ctx = context(seed)
    entity = new_id("problem", SeededIdSource(seed + "/entity"))
    res = reserve_alias(
        store, lambda s: plan_external_alias(POLICY, s, scheme_id="erdos", external_identifier=number, entity_id=entity), ctx
    )
    bind_alias(store, res.alias, entity, ctx)
    return store, res.alias, entity
