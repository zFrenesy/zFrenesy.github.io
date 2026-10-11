"""Permanent human-readable aliases (§3, docs/adr/0003).

Grammar::

    problem       <PREFIX>-<local>             ERDOS-5, ECON-C73-1, MATH-12
    subproblem    <problem>.<k>[.<k>...]       ERDOS-5.2, ERDOS-5.2.1
    contribution  <problem>-A<k> | -R<k>       ERDOS-5-A4, ERDOS-5.2-R1

Each scheme states its allocation authority: ``external_identifier`` schemes
copy an identifier assigned by an outside catalogue (the alias does not claim
the catalogue recognises the record); ``counter`` schemes are minted by the
platform. Subproblem and contribution numbers come from per-parent counters.

Aliases live in one global namespace. A reservation is permanent: abandoned
aliases leave gaps and are never recycled, and hierarchical aliases record
registration lineage, so reparenting never renames anything. Resolution is
an exact registry lookup, never a guess from the grammar.

Everything here is pure: planners read a registry view and return the
reservation to record. The ledger (rp.ledger) makes it durable and
serialises concurrent planners with compare-and-swap appends.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol

from rp.identity.ids import id_kind, is_id
from rp.vocab import contribution_alias_letter

__all__ = [
    "AliasError",
    "AliasParts",
    "AliasPolicy",
    "AliasRecord",
    "AliasRegistryView",
    "AliasReservation",
    "AliasScheme",
    "normalise_alias",
    "plan_abandon",
    "plan_bind",
    "plan_contribution_alias",
    "plan_counter_alias",
    "plan_external_alias",
    "plan_subproblem_alias",
    "resolve_alias",
]

ALLOCATIONS = ("external_identifier", "counter")
STATES = ("reserved", "bound", "abandoned")
MAX_SUBPROBLEM_DEPTH = 8
_PREFIX = re.compile(r"[A-Z][A-Z0-9]{1,9}")
_COUNTER_LOCAL = "[1-9][0-9]*"


class AliasError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class AliasScheme:
    id: str
    prefix: str
    allocation: str
    allocation_authority: str
    local_pattern: str = _COUNTER_LOCAL
    enabled: bool = True
    external_scheme: str | None = None


@dataclass(frozen=True, slots=True)
class AliasParts:
    alias: str
    scheme_id: str
    prefix: str
    local: str
    subpath: tuple[int, ...]
    letter: str | None
    number: int | None

    @property
    def is_contribution(self) -> bool:
        return self.letter is not None

    @property
    def problem_alias(self) -> str:
        return f"{self.prefix}-{self.local}" + "".join(f".{k}" for k in self.subpath)

    @property
    def parent_alias(self) -> str | None:
        if self.is_contribution:
            return self.problem_alias
        if not self.subpath:
            return None
        return f"{self.prefix}-{self.local}" + "".join(f".{k}" for k in self.subpath[:-1])


def normalise_alias(text: str) -> str:
    """Normalise user input. Valid aliases are upper-case ASCII, so upper-casing is lossless."""
    if not isinstance(text, str):
        raise AliasError("alias.grammar", "alias must be a string")
    return text.strip().upper()


class AliasPolicy:
    """The configured alias schemes, with their grammar."""

    def __init__(self, schemes: Iterable[AliasScheme], *, platform_authority: str):
        self.platform_authority = platform_authority
        self.schemes: dict[str, AliasScheme] = {}
        self._patterns: list[tuple[AliasScheme, re.Pattern[str]]] = []
        counters: dict[str, str] = {}
        for scheme in schemes:
            if scheme.id in self.schemes:
                raise AliasError("alias.config", f"duplicate scheme id {scheme.id!r}")
            if not _PREFIX.fullmatch(scheme.prefix):
                raise AliasError("alias.config", f"invalid prefix {scheme.prefix!r}")
            if scheme.allocation not in ALLOCATIONS:
                raise AliasError("alias.config", f"unknown allocation {scheme.allocation!r}")
            if scheme.allocation == "counter":
                if scheme.local_pattern != _COUNTER_LOCAL:
                    raise AliasError("alias.config", f"counter scheme {scheme.id!r} must use {_COUNTER_LOCAL}")
                if scheme.prefix in counters:
                    raise AliasError("alias.config", f"prefix {scheme.prefix} has two counter schemes")
                counters[scheme.prefix] = scheme.id
            local = re.compile(scheme.local_pattern)
            if local.fullmatch("") or any(c in scheme.local_pattern for c in "()."):
                # Groups or dots in local patterns would make subproblem suffixes ambiguous.
                raise AliasError("alias.config", f"scheme {scheme.id!r} local pattern must not contain groups or '.'")
            pattern = re.compile(
                rf"{scheme.prefix}-(?P<local>{scheme.local_pattern})"
                rf"(?P<sub>(?:\.[1-9][0-9]*)*)(?:-(?P<letter>[AR])(?P<num>[1-9][0-9]*))?"
            )
            self.schemes[scheme.id] = scheme
            self._patterns.append((scheme, pattern))
        for scheme in self.schemes.values():
            counter_id = counters.get(scheme.prefix)
            if scheme.allocation == "external_identifier" and counter_id is not None:
                local = re.compile(scheme.local_pattern)
                if any(local.fullmatch(str(n)) for n in range(1, 10_000)):
                    raise AliasError(
                        "alias.config",
                        f"scheme {scheme.id!r} shares prefix {scheme.prefix} with counter scheme "
                        f"{counter_id!r} and could mint the same aliases",
                    )

    def counter_scheme(self, prefix: str) -> AliasScheme:
        for scheme in self.schemes.values():
            if scheme.prefix == prefix and scheme.allocation == "counter":
                return scheme
        raise AliasError("alias.unknown_scheme", f"no counter scheme for prefix {prefix!r}")

    def scheme(self, scheme_id: str) -> AliasScheme:
        try:
            return self.schemes[scheme_id]
        except KeyError:
            raise AliasError("alias.unknown_scheme", f"unknown alias scheme {scheme_id!r}") from None

    def parse(self, alias: str) -> AliasParts:
        matches = []
        for scheme, pattern in self._patterns:
            m = pattern.fullmatch(alias)
            if m:
                matches.append((scheme, m))
        if not matches:
            raise AliasError("alias.grammar", f"{alias!r} does not match any alias scheme")
        if len(matches) > 1:
            names = ", ".join(s.id for s, _ in matches)
            raise AliasError("alias.config", f"{alias!r} matches several schemes ({names})")
        scheme, m = matches[0]
        subpath = tuple(int(k) for k in m.group("sub").split(".")[1:])
        if len(subpath) > MAX_SUBPROBLEM_DEPTH:
            raise AliasError("alias.grammar", f"{alias!r} nests deeper than {MAX_SUBPROBLEM_DEPTH} levels")
        return AliasParts(
            alias=alias,
            scheme_id=scheme.id,
            prefix=scheme.prefix,
            local=m.group("local"),
            subpath=subpath,
            letter=m.group("letter"),
            number=int(m.group("num")) if m.group("num") else None,
        )


@dataclass(frozen=True, slots=True)
class AliasRecord:
    alias: str
    entity_id: str
    scheme_id: str
    allocation_authority: str
    parent_alias: str | None
    counter_key: str | None
    sequence: int | None
    external_identifier: str | None
    state: str
    reserved_by: str


class AliasRegistryView(Protocol):
    def alias_record(self, alias: str) -> AliasRecord | None: ...

    def counter_value(self, key: str) -> int: ...

    def live_alias_of(self, entity_id: str) -> str | None:
        """The entity's reserved or bound primary alias, ignoring abandoned ones."""
        ...


@dataclass(frozen=True, slots=True)
class AliasReservation:
    alias: str
    entity_id: str
    scheme_id: str
    allocation_authority: str
    parent_alias: str | None
    counter_key: str | None
    sequence: int | None
    external_identifier: str | None
    existing: bool = field(default=False, compare=False)

    def payload(self) -> dict:
        return {
            "alias": self.alias,
            "entity_id": self.entity_id,
            "scheme_id": self.scheme_id,
            "allocation_authority": self.allocation_authority,
            "parent_alias": self.parent_alias,
            "counter_key": self.counter_key,
            "sequence": self.sequence,
            "external_identifier": self.external_identifier,
        }


def _existing(registry: AliasRegistryView, entity_id: str) -> AliasReservation | None:
    alias = registry.live_alias_of(entity_id)
    if alias is None:
        return None
    rec = registry.alias_record(alias)
    assert rec is not None
    return AliasReservation(
        rec.alias,
        rec.entity_id,
        rec.scheme_id,
        rec.allocation_authority,
        rec.parent_alias,
        rec.counter_key,
        rec.sequence,
        rec.external_identifier,
        existing=True,
    )


def _require_entity(entity_id: str, kind: str) -> None:
    if not is_id(entity_id, kind):
        raise AliasError("alias.entity_kind", f"{entity_id!r} is not a {kind} identifier")


def _next_free(registry: AliasRegistryView, key: str, make) -> tuple[int, str]:
    seq = registry.counter_value(key) + 1
    while registry.alias_record(make(seq)) is not None:
        seq += 1
    return seq, make(seq)


def _bound_problem(policy: AliasPolicy, registry: AliasRegistryView, alias: str) -> AliasRecord:
    alias = normalise_alias(alias)
    parts = policy.parse(alias)
    if parts.is_contribution:
        raise AliasError("alias.entity_kind", f"{alias} is a contribution alias, not a problem alias")
    rec = registry.alias_record(alias)
    if rec is None or rec.state != "bound" or id_kind(rec.entity_id) != "problem":
        raise AliasError("alias.parent_not_bound", f"{alias} is not a bound problem alias")
    return rec


def plan_counter_alias(
    policy: AliasPolicy, registry: AliasRegistryView, *, prefix: str, entity_id: str
) -> AliasReservation:
    """Mint ``<PREFIX>-<n>`` for a new top-level problem (literature or proposed)."""
    _require_entity(entity_id, "problem")
    if (found := _existing(registry, entity_id)) is not None:
        return found
    scheme = policy.counter_scheme(prefix)
    if not scheme.enabled:
        raise AliasError("alias.scheme_disabled", f"scheme {scheme.id!r} is not accepting new problems")
    key = f"top:{prefix}"
    seq, alias = _next_free(registry, key, lambda n: f"{prefix}-{n}")
    return AliasReservation(alias, entity_id, scheme.id, scheme.allocation_authority, None, key, seq, None)


def plan_external_alias(
    policy: AliasPolicy, registry: AliasRegistryView, *, scheme_id: str, external_identifier: str, entity_id: str
) -> AliasReservation:
    """Reserve ``<PREFIX>-<external id>`` for a catalogued problem."""
    _require_entity(entity_id, "problem")
    if (found := _existing(registry, entity_id)) is not None:
        return found
    scheme = policy.scheme(scheme_id)
    if scheme.allocation != "external_identifier":
        raise AliasError("alias.unknown_scheme", f"scheme {scheme_id!r} does not copy external identifiers")
    if not isinstance(external_identifier, str) or not re.fullmatch(scheme.local_pattern, external_identifier):
        raise AliasError("alias.grammar", f"{external_identifier!r} is not a valid {scheme_id} identifier")
    alias = f"{scheme.prefix}-{external_identifier}"
    rec = registry.alias_record(alias)
    if rec is not None:
        code = "alias.burned" if rec.state == "abandoned" else "alias.taken"
        raise AliasError(code, f"{alias} is already {rec.state} for {rec.entity_id}")
    return AliasReservation(
        alias, entity_id, scheme.id, scheme.allocation_authority, None, None, None, external_identifier
    )


def plan_subproblem_alias(
    policy: AliasPolicy, registry: AliasRegistryView, *, parent_alias: str, entity_id: str
) -> AliasReservation:
    """Mint ``<parent>.<k>``: the k-th subproblem registered under the parent."""
    _require_entity(entity_id, "problem")
    if (found := _existing(registry, entity_id)) is not None:
        return found
    parent = _bound_problem(policy, registry, parent_alias)
    parts = policy.parse(parent.alias)
    if len(parts.subpath) >= MAX_SUBPROBLEM_DEPTH:
        raise AliasError("alias.grammar", f"subproblems of {parent.alias} would nest too deeply")
    key = f"sub:{parent.alias}"
    seq, alias = _next_free(registry, key, lambda n: f"{parent.alias}.{n}")
    scheme = policy.scheme(parts.scheme_id)
    return AliasReservation(alias, entity_id, scheme.id, policy.platform_authority, parent.alias, key, seq, None)


def plan_contribution_alias(
    policy: AliasPolicy,
    registry: AliasRegistryView,
    *,
    home_problem_alias: str,
    contribution_type: str,
    entity_id: str,
) -> AliasReservation:
    """Mint ``<problem>-A<k>`` or ``<problem>-R<k>`` on the contribution's home problem."""
    _require_entity(entity_id, "contribution")
    if (found := _existing(registry, entity_id)) is not None:
        return found
    home = _bound_problem(policy, registry, home_problem_alias)
    letter = contribution_alias_letter(contribution_type)
    key = f"con:{home.alias}:{letter}"
    seq, alias = _next_free(registry, key, lambda n: f"{home.alias}-{letter}{n}")
    scheme_id = policy.parse(home.alias).scheme_id
    return AliasReservation(alias, entity_id, scheme_id, policy.platform_authority, home.alias, key, seq, None)


def plan_bind(registry: AliasRegistryView, *, alias: str, entity_id: str) -> bool:
    """Check that ``alias`` may be bound to ``entity_id``. Returns False when it already is."""
    rec = registry.alias_record(normalise_alias(alias))
    if rec is None:
        raise AliasError("alias.unknown", f"{alias} is not reserved")
    if rec.entity_id != entity_id:
        raise AliasError("alias.taken", f"{alias} is reserved for {rec.entity_id}")
    if rec.state == "abandoned":
        raise AliasError("alias.burned", f"{alias} was abandoned and cannot be bound")
    return rec.state == "reserved"


def plan_abandon(registry: AliasRegistryView, *, alias: str) -> bool:
    """Check that ``alias`` may be abandoned. Returns False when it already is."""
    rec = registry.alias_record(normalise_alias(alias))
    if rec is None:
        raise AliasError("alias.unknown", f"{alias} is not reserved")
    if rec.state == "bound":
        raise AliasError("alias.permanent", f"{alias} is bound; bound aliases are permanent")
    return rec.state == "reserved"


def resolve_alias(policy: AliasPolicy, registry: AliasRegistryView, text: str) -> AliasRecord:
    alias = normalise_alias(text)
    policy.parse(alias)
    rec = registry.alias_record(alias)
    if rec is None:
        raise AliasError("alias.unknown", f"{alias} is not a reserved alias")
    return rec
