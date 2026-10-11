import dataclasses

import pytest

from rp.identity.aliases import (
    AliasError,
    AliasPolicy,
    AliasRecord,
    AliasScheme,
    plan_abandon,
    plan_bind,
    plan_contribution_alias,
    plan_counter_alias,
    plan_external_alias,
    plan_subproblem_alias,
    resolve_alias,
)
from rp.identity.ids import SeededIdSource, new_id

SCHEMES = [
    AliasScheme("erdos", "ERDOS", "external_identifier", "erdosproblems.com", "[1-9][0-9]*"),
    AliasScheme("economics-legacy", "ECON", "external_identifier", "legacy-economics", "[A-Z][0-9]{1,2}-[1-9][0-9]*"),
    AliasScheme("discipline:mathematics", "MATH", "counter", "we-solve"),
    AliasScheme("discipline:economics", "ECON", "counter", "we-solve"),
    AliasScheme("discipline:biology", "BIO", "counter", "we-solve", enabled=False),
]
POLICY = AliasPolicy(SCHEMES, platform_authority="we-solve")
IDS = SeededIdSource("aliases")


class Registry:
    """Minimal in-memory registry view; the ledger's derived state is the real one."""

    def __init__(self):
        self.records: dict[str, AliasRecord] = {}
        self.counters: dict[str, int] = {}

    def alias_record(self, alias):
        return self.records.get(alias)

    def counter_value(self, key):
        return self.counters.get(key, 0)

    def live_alias_of(self, entity_id):
        for rec in self.records.values():
            if rec.entity_id == entity_id and rec.state != "abandoned":
                return rec.alias
        return None

    def apply(self, reservation, state="reserved"):
        self.records[reservation.alias] = AliasRecord(**reservation.payload(), state=state, reserved_by="evt")
        if reservation.counter_key:
            self.counters[reservation.counter_key] = max(self.counter_value(reservation.counter_key), reservation.sequence)
        return reservation.alias

    def set_state(self, alias, state):
        self.records[alias] = dataclasses.replace(self.records[alias], state=state)


def prb():
    return new_id("problem", IDS)


def con():
    return new_id("contribution", IDS)


@pytest.fixture
def reg():
    r = Registry()
    erdos5 = r.apply(plan_external_alias(POLICY, r, scheme_id="erdos", external_identifier="5", entity_id=prb()))
    r.set_state(erdos5, "bound")
    econ = r.apply(plan_external_alias(POLICY, r, scheme_id="economics-legacy", external_identifier="C73-1", entity_id=prb()))
    r.set_state(econ, "bound")
    return r


@pytest.mark.parametrize(
    "alias, scheme, problem, parent, letter",
    [
        ("ERDOS-5", "erdos", "ERDOS-5", None, None),
        ("ERDOS-5.2", "erdos", "ERDOS-5.2", "ERDOS-5", None),
        ("ERDOS-5.2.1", "erdos", "ERDOS-5.2.1", "ERDOS-5.2", None),
        ("ERDOS-5-A4", "erdos", "ERDOS-5", "ERDOS-5", "A"),
        ("ERDOS-5.2-R1", "erdos", "ERDOS-5.2", "ERDOS-5.2", "R"),
        ("ECON-C73-1", "economics-legacy", "ECON-C73-1", None, None),
        ("ECON-C73-1-A4", "economics-legacy", "ECON-C73-1", "ECON-C73-1", "A"),
        ("ECON-12", "discipline:economics", "ECON-12", None, None),
        ("ECON-12-R3", "discipline:economics", "ECON-12", "ECON-12", "R"),
        ("MATH-12.3", "discipline:mathematics", "MATH-12.3", "MATH-12", None),
    ],
)
def test_parse(alias, scheme, problem, parent, letter):
    parts = POLICY.parse(alias)
    assert (parts.scheme_id, parts.problem_alias, parts.parent_alias, parts.letter) == (scheme, problem, parent, letter)


@pytest.mark.parametrize(
    "alias",
    ["ERDOS-0", "ERDOS-05", "erdos-5", "ERDOS-5.0", "ERDOS-5-B1", "ERDOS-5-A0", "MATH-", "ECON-C73", "FOO-1", "ERDOS-5" + ".1" * 9],
)
def test_parse_rejects(alias):
    with pytest.raises(AliasError):
        POLICY.parse(alias)


def test_policy_rejects_overlapping_schemes():
    with pytest.raises(AliasError, match="could mint the same aliases"):
        AliasPolicy(
            [AliasScheme("x", "MATH", "external_identifier", "x", "[0-9]+"), AliasScheme("c", "MATH", "counter", "we-solve")],
            platform_authority="we-solve",
        )
    with pytest.raises(AliasError):
        AliasPolicy(
            [AliasScheme("g", "X", "external_identifier", "x", "(a|b)")], platform_authority="we-solve"
        )


def test_counter_aliases_are_sequential_and_never_recycled(reg):
    a = plan_counter_alias(POLICY, reg, prefix="MATH", entity_id=prb())
    assert a.alias == "MATH-1" and a.allocation_authority == "we-solve"
    reg.apply(a)
    plan_abandon(reg, alias="MATH-1")
    reg.set_state("MATH-1", "abandoned")
    b = plan_counter_alias(POLICY, reg, prefix="MATH", entity_id=prb())
    assert b.alias == "MATH-2"


def test_counter_reservation_is_idempotent_per_entity(reg):
    entity = prb()
    first = plan_counter_alias(POLICY, reg, prefix="MATH", entity_id=entity)
    reg.apply(first)
    again = plan_counter_alias(POLICY, reg, prefix="MATH", entity_id=entity)
    assert again.alias == first.alias and again.existing


def test_disabled_scheme(reg):
    with pytest.raises(AliasError) as info:
        plan_counter_alias(POLICY, reg, prefix="BIO", entity_id=prb())
    assert info.value.code == "alias.scheme_disabled"


def test_external_alias_conflicts(reg):
    with pytest.raises(AliasError) as info:
        plan_external_alias(POLICY, reg, scheme_id="erdos", external_identifier="5", entity_id=prb())
    assert info.value.code == "alias.taken"
    with pytest.raises(AliasError):
        plan_external_alias(POLICY, reg, scheme_id="erdos", external_identifier="05", entity_id=prb())


def test_abandoned_external_alias_is_burned(reg):
    reg.apply(plan_external_alias(POLICY, reg, scheme_id="erdos", external_identifier="7", entity_id=prb()))
    reg.set_state("ERDOS-7", "abandoned")
    with pytest.raises(AliasError) as info:
        plan_external_alias(POLICY, reg, scheme_id="erdos", external_identifier="7", entity_id=prb())
    assert info.value.code == "alias.burned"


def test_subproblem_and_contribution_aliases(reg):
    sub = plan_subproblem_alias(POLICY, reg, parent_alias="erdos-5", entity_id=prb())
    assert (sub.alias, sub.parent_alias, sub.allocation_authority) == ("ERDOS-5.1", "ERDOS-5", "we-solve")
    reg.apply(sub)
    with pytest.raises(AliasError) as info:
        plan_subproblem_alias(POLICY, reg, parent_alias="ERDOS-5.1", entity_id=prb())
    assert info.value.code == "alias.parent_not_bound"
    reg.set_state("ERDOS-5.1", "bound")
    assert plan_subproblem_alias(POLICY, reg, parent_alias="ERDOS-5.1", entity_id=prb()).alias == "ERDOS-5.1.1"

    attempts = [reg.apply(plan_contribution_alias(POLICY, reg, home_problem_alias="ERDOS-5", contribution_type=t, entity_id=con()))
                for t in ("attempt", "counterexample", "review", "author_response", "legacy_record")]
    assert attempts == ["ERDOS-5-A1", "ERDOS-5-A2", "ERDOS-5-R1", "ERDOS-5-R2", "ERDOS-5-A3"]
    econ = plan_contribution_alias(POLICY, reg, home_problem_alias="ECON-C73-1", contribution_type="attempt", entity_id=con())
    assert econ.alias == "ECON-C73-1-A1"


def test_contribution_alias_requires_contribution_entity(reg):
    with pytest.raises(AliasError) as info:
        plan_contribution_alias(POLICY, reg, home_problem_alias="ERDOS-5", contribution_type="attempt", entity_id=prb())
    assert info.value.code == "alias.entity_kind"


def test_bind_and_abandon_rules(reg):
    entity = prb()
    reg.apply(plan_counter_alias(POLICY, reg, prefix="MATH", entity_id=entity))
    assert plan_bind(reg, alias="MATH-1", entity_id=entity) is True
    with pytest.raises(AliasError):
        plan_bind(reg, alias="MATH-1", entity_id=prb())
    reg.set_state("MATH-1", "bound")
    assert plan_bind(reg, alias="MATH-1", entity_id=entity) is False
    with pytest.raises(AliasError) as info:
        plan_abandon(reg, alias="MATH-1")
    assert info.value.code == "alias.permanent"


def test_resolution_is_exact_lookup(reg):
    assert resolve_alias(POLICY, reg, " erdos-5 ").alias == "ERDOS-5"
    with pytest.raises(AliasError) as info:
        resolve_alias(POLICY, reg, "ERDOS-6")
    assert info.value.code == "alias.unknown"
