import copy

import pytest

from rp.canonical import digest
from rp.identity.aliases import AliasError, plan_contribution_alias, plan_counter_alias, plan_subproblem_alias
from rp.identity.ids import SeededIdSource, new_id
from rp.ledger.events import EventError, idempotency_key, make_event
from rp.ledger.operations import abandon_alias, accept_revision, bind_alias, reserve_alias
from rp.ledger.state import LedgerCorruption, StalePredecessor, rebuild
from rp.ledger.store import GENESIS, IdempotencyConflict, LedgerConflict, MemoryLedger
from rp.timeutil import DateClaim, FixedClock
from tests.ledger_helpers import ACTOR, POLICY, context, ledger_with_bound_problem

IDS = SeededIdSource("ledger-unit")


def event(seed="e", **overrides):
    ctx = context(seed)
    entity = overrides.pop("entity", new_id("problem", IDS))
    kwargs = dict(
        event_type="external_id_mapped",
        actor=ACTOR,
        targets=[entity],
        payload={"entity_id": entity, "scheme": "erdosproblems", "identifier": "5", "authority": "erdosproblems.com"},
        scope={"entity_id": entity},
        policy_version="policy/1",
        clock=ctx.clock,
        id_source=ctx.id_source,
    )
    kwargs.update(overrides)
    return make_event(**kwargs)


def test_make_event_defaults_and_validation():
    e = event()
    assert e["occurred_at"] == {"value": "2026-10-11T00:00:00Z", "precision": "instant"}
    assert e["recorded_at"] == "2026-10-11T00:00:00Z"
    with pytest.raises(EventError):
        event(payload={"entity_id": "nope"})
    with pytest.raises(EventError):
        event(time_source="system_clock", occurred_at=DateClaim("2026-10-01", "day"))


def test_declared_dates_keep_their_precision():
    entity = new_id("contribution", IDS)
    e = event(
        event_type="date_declared",
        targets=[entity],
        payload={"subject_id": entity, "kind": "first_posted", "claim": {"value": "2026-10-09", "precision": "day"}},
        scope={"subject_id": entity, "kind": "first_posted"},
        occurred_at=DateClaim("2026-10-09", "day"),
        time_source="legacy_header",
    )
    assert e["occurred_at"]["precision"] == "day"
    assert e["recorded_at"].endswith("Z")


def test_idempotency_key_depends_on_request_only():
    assert idempotency_key("alias_reserved", {"a": 1}) == idempotency_key("alias_reserved", {"a": 1})
    assert idempotency_key("alias_reserved", {"a": 1}) != idempotency_key("alias_reserved", {"a": 2})
    assert idempotency_key("alias_reserved", {"a": 1}, "run-1") != idempotency_key("alias_reserved", {"a": 1}, "run-2")
    assert idempotency_key("alias_bound", {"a": 1}) != idempotency_key("alias_reserved", {"a": 1})


def test_store_compare_and_swap():
    store = MemoryLedger()
    head, events = store.read()
    assert (head, events) == (GENESIS, [])
    first = store.append(head, [event("one")])
    with pytest.raises(LedgerConflict):
        store.append(head, [event("two")])
    store.append(first.head, [event("two")])
    assert len(store.read()[1]) == 2


def test_store_idempotent_append():
    store = MemoryLedger()
    entity = new_id("problem", IDS)
    original = event("x", entity=entity)
    store.append(GENESIS, [original])
    replay = event("y", entity=entity)  # new event id and clock, same request
    assert replay["event_id"] != original["event_id"]
    result = store.append(GENESIS, [replay])  # stale head is fine: nothing new to write
    assert result.appended == () and result.existing[0]["event_id"] == original["event_id"]
    different = event("z", entity=entity, payload={**original["payload"], "identifier": "6"})
    with pytest.raises(IdempotencyConflict):
        store.append(store.read()[0], [different])


def test_store_rejects_invalid_and_duplicate_ids():
    store = MemoryLedger()
    bad = event()
    bad["payload"]["identifier"] = ""
    with pytest.raises(EventError):
        store.append(GENESIS, [bad])
    e = event("dup")
    store.append(GENESIS, [e])
    clone = copy.deepcopy(e)
    clone["idempotency_key"] = digest("other")
    with pytest.raises(IdempotencyConflict):
        store.append(store.read()[0], [clone])


def test_head_is_a_hash_chain_and_export_round_trips():
    store, _, _ = ledger_with_bound_problem("chain")
    head, events = store.read()
    again = MemoryLedger.from_events(events)
    assert again.read()[0] == head
    assert again.export_jsonl() == store.export_jsonl()
    tampered = copy.deepcopy(events)
    tampered[0]["recorded_at"] = "2026-10-11T00:00:59Z"
    assert MemoryLedger.from_events(tampered).read()[0] != head


def test_alias_lifecycle_through_the_ledger():
    store, parent, _ = ledger_with_bound_problem("life")
    ctx = context("life-ops")
    sub_entity = new_id("problem", IDS)
    sub = reserve_alias(store, lambda s: plan_subproblem_alias(POLICY, s, parent_alias=parent, entity_id=sub_entity), ctx)
    assert sub.alias == "ERDOS-5.1"
    assert abandon_alias(store, sub.alias, sub_entity, "candidate_closed", ctx) is True
    assert abandon_alias(store, sub.alias, sub_entity, "candidate_closed", ctx) is False
    with pytest.raises(AliasError):
        bind_alias(store, sub.alias, sub_entity, ctx)
    nxt = reserve_alias(store, lambda s: plan_subproblem_alias(POLICY, s, parent_alias=parent, entity_id=new_id("problem", IDS)), ctx)
    assert nxt.alias == "ERDOS-5.2"  # the abandoned ERDOS-5.1 is never recycled
    state = rebuild(store.read()[1])
    assert state.alias_record("ERDOS-5.1").state == "abandoned"
    assert state.alias_record("ERDOS-5").state == "bound"


def test_reservation_is_idempotent_per_entity():
    store, parent, _ = ledger_with_bound_problem("idem")
    ctx = context("idem-ops")
    entity = new_id("contribution", IDS)

    def plan(s):
        return plan_contribution_alias(POLICY, s, home_problem_alias=parent, contribution_type="attempt", entity_id=entity)

    first = reserve_alias(store, plan, ctx)
    second = reserve_alias(store, plan, ctx)
    assert first.alias == second.alias == "ERDOS-5-A1" and second.existing
    assert sum(e["type"] == "alias_reserved" for e in store.read()[1]) == 2  # ERDOS-5 and ERDOS-5-A1


def test_counter_alias_for_planned_discipline_is_refused():
    store = MemoryLedger()
    with pytest.raises(AliasError):
        reserve_alias(store, lambda s: plan_counter_alias(POLICY, s, prefix="BIO", entity_id=new_id("problem", IDS)), context("bio"))
    assert store.read()[1] == []


def test_revisions_advance_only_from_the_current_head():
    store = MemoryLedger()
    ctx = context("revs")
    con = new_id("contribution", IDS)
    r1, r2, r2b = (new_id("revision", IDS) for _ in range(3))
    common = dict(scientific_fingerprint=digest("s"), authorization_binding=digest("k"), ctx=ctx)
    assert accept_revision(store, contribution_id=con, revision_id=r1, expected_predecessor=None, **common) == "r1"
    assert accept_revision(store, contribution_id=con, revision_id=r2, expected_predecessor=r1, **common) == "r2"
    with pytest.raises(StalePredecessor):
        accept_revision(store, contribution_id=con, revision_id=r2b, expected_predecessor=r1, **common)
    # Replaying an accepted revision returns its label without appending.
    before = store.read()[0]
    assert accept_revision(store, contribution_id=con, revision_id=r1, expected_predecessor=None, **common) == "r1"
    assert store.read()[0] == before
    state = rebuild(store.read()[1])
    assert state.revision_heads[con] == r2 and state.revision_labels == {r1: "r1", r2: "r2"}


def test_rebuild_detects_corrupt_histories():
    store, _, entity = ledger_with_bound_problem("corrupt")
    events = store.read()[1]
    with pytest.raises(LedgerCorruption):
        rebuild(events + [copy.deepcopy(events[0])])
    with pytest.raises(LedgerCorruption):
        rebuild([events[1]])  # bound before reserved


def test_snapshot_activation_is_serialised():
    clock = FixedClock("2026-10-11T00:00:00Z")
    pub1, pub2, pub3 = (new_id("publication_snapshot", IDS) for _ in range(3))

    def activation(snapshot, previous):
        return make_event(
            event_type="snapshot_activated",
            actor=ACTOR,
            targets=[snapshot],
            payload={"snapshot_id": snapshot, "previous_snapshot_id": previous, "deployment": {"repository": "we-solve/we-solve.github.io", "run_id": 1}},
            scope={"snapshot_id": snapshot},
            policy_version="policy/1",
            clock=clock,
        )

    state = rebuild([activation(pub1, None), activation(pub2, pub1)])
    assert state.active_snapshot == pub2
    with pytest.raises(LedgerCorruption):
        rebuild([activation(pub1, None), activation(pub2, pub1), activation(pub3, pub1)])  # stale replacement
