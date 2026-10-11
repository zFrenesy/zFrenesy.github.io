"""Concurrency and crash drills for the ledger (§12 acceptance tests, pure-logic part).

The in-memory store is wrapped so that every append yields the GIL between
reading and writing, which forces many compare-and-swap conflicts.
"""

import threading
import time

import pytest

from rp.canonical import digest
from rp.identity.aliases import plan_contribution_alias, plan_subproblem_alias
from rp.identity.ids import SeededIdSource, new_id
from rp.ledger.operations import accept_revision, reserve_alias
from rp.ledger.state import StalePredecessor, rebuild
from rp.ledger.store import LedgerConflict, MemoryLedger
from tests.ledger_helpers import POLICY, context, ledger_with_bound_problem

pytestmark = pytest.mark.stress


class ContendedLedger(MemoryLedger):
    def __init__(self, inner: MemoryLedger):
        super().__init__()
        self._inner = inner
        self.conflicts = 0
        self._count_lock = threading.Lock()

    def read(self):
        return self._inner.read()

    def append(self, expected_head, events):
        time.sleep(0.0002)
        try:
            return self._inner.append(expected_head, events)
        except LedgerConflict:
            with self._count_lock:
                self.conflicts += 1
            raise


def run_threads(n, target):
    barrier = threading.Barrier(n)
    results, errors = [None] * n, []

    def worker(i):
        barrier.wait()
        try:
            results[i] = target(i)
        except Exception as exc:  # noqa: BLE001 - surfaced by the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors, errors[:3]
    return results


@pytest.mark.parametrize("run", range(20))
def test_fifty_concurrent_sibling_proposals_get_distinct_permanent_aliases(run):
    inner, parent, _ = ledger_with_bound_problem(f"siblings-{run}")
    store = ContendedLedger(inner)
    ids = SeededIdSource(f"siblings-{run}/entities")
    entities = [new_id("problem", ids) for _ in range(50)]

    def propose(i):
        ctx = context(f"siblings-{run}/{i}")
        return reserve_alias(store, lambda s: plan_subproblem_alias(POLICY, s, parent_alias=parent, entity_id=entities[i]), ctx).alias

    aliases = run_threads(50, propose)
    assert sorted(aliases, key=lambda a: int(a.split(".")[1])) == [f"{parent}.{k}" for k in range(1, 51)]
    assert store.conflicts > 0, "the drill must actually produce compare-and-swap conflicts"
    state = rebuild(inner.read()[1])
    assert {state.live_alias_of(e) for e in entities} == set(aliases)
    assert state.counter_value(f"sub:{parent}") == 50


def test_repeated_workflow_runs_lose_nothing_and_duplicate_nothing():
    inner, parent, _ = ledger_with_bound_problem("repeat")
    store = ContendedLedger(inner)
    ids = SeededIdSource("repeat/entities")
    entities = [new_id("contribution", ids) for _ in range(25)]

    def run(i):
        entity = entities[i % 25]  # every request is delivered twice, concurrently
        ctx = context(f"repeat/{i}")
        plan = lambda s: plan_contribution_alias(  # noqa: E731
            POLICY, s, home_problem_alias=parent, contribution_type="attempt", entity_id=entity
        )
        return entity, reserve_alias(store, plan, ctx).alias

    results = run_threads(50, run)
    by_entity = {}
    for entity, alias in results:
        by_entity.setdefault(entity, set()).add(alias)
    assert all(len(aliases) == 1 for aliases in by_entity.values())
    assert sorted(a.pop() for a in by_entity.values()) == sorted(f"{parent}-A{k}" for k in range(1, 26))
    reservations = [e for e in inner.read()[1] if e["type"] == "alias_reserved"]
    assert len(reservations) == 26  # the parent plus one per entity


class DropsResponses(MemoryLedger):
    """Writes succeed but the first ``drops`` responses are lost, like a runner dying after the push."""

    def __init__(self, inner: MemoryLedger, drops: int):
        super().__init__()
        self._inner = inner
        self._drops = drops

    def read(self):
        return self._inner.read()

    def append(self, expected_head, events):
        result = self._inner.append(expected_head, events)
        if self._drops and result.appended:
            self._drops -= 1
            raise ConnectionError("response lost after the write landed")
        return result


def test_dropped_run_after_write_is_recovered_without_duplicates():
    inner, parent, _ = ledger_with_bound_problem("dropped")
    entity = new_id("problem", SeededIdSource("dropped/subproblem"))
    flaky = DropsResponses(inner, drops=1)

    def plan(s):
        return plan_subproblem_alias(POLICY, s, parent_alias=parent, entity_id=entity)

    with pytest.raises(ConnectionError):
        reserve_alias(flaky, plan, context("dropped/1"))
    retried = reserve_alias(flaky, plan, context("dropped/2"))  # the rerun of the workflow
    assert retried.alias == f"{parent}.1" and retried.existing
    assert sum(e["type"] == "alias_reserved" for e in inner.read()[1]) == 2


def test_concurrent_revisions_with_the_same_predecessor_cannot_both_advance():
    for run in range(10):
        inner = MemoryLedger()
        store = ContendedLedger(inner)
        ids = SeededIdSource(f"race-{run}")
        con, r1 = new_id("contribution", ids), new_id("revision", ids)
        accept_revision(
            inner,
            contribution_id=con,
            revision_id=r1,
            expected_predecessor=None,
            scientific_fingerprint=digest("s1"),
            authorization_binding=digest("k1"),
            ctx=context(f"race-{run}/base"),
        )
        rivals = [new_id("revision", ids) for _ in range(8)]

        def attempt(i):
            try:
                return accept_revision(
                    store,
                    contribution_id=con,
                    revision_id=rivals[i],
                    expected_predecessor=r1,
                    scientific_fingerprint=digest(f"s{i}"),
                    authorization_binding=digest(f"k{i}"),
                    ctx=context(f"race-{run}/{i}"),
                )
            except StalePredecessor:
                return None

        labels = run_threads(8, attempt)
        assert labels.count("r2") == 1 and labels.count(None) == 7
        state = rebuild(inner.read()[1])
        assert state.revision_heads[con] == rivals[labels.index("r2")]
