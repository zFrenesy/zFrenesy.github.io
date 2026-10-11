"""Derived ledger state, rebuilt from events alone (§9).

Nothing here is authoritative on its own: ``rebuild`` replays the event log
and must reproduce the same state every time. Events that contradict the
state they apply to (a second reservation of an alias, a revision that does
not extend the current head) indicate a corrupt ledger and raise.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from rp.identity.aliases import AliasRecord

__all__ = ["LedgerCorruption", "LedgerState", "StalePredecessor", "rebuild"]


class LedgerCorruption(Exception):
    pass


class StalePredecessor(Exception):
    """A revision's expected predecessor is no longer the accepted head."""

    def __init__(self, subject: str, expected: str | None, actual: str | None):
        self.subject = subject
        self.expected = expected
        self.actual = actual
        super().__init__(f"{subject}: expected predecessor {expected}, but the accepted head is {actual}")


@dataclass
class LedgerState:
    aliases: dict[str, AliasRecord] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)
    entity_aliases: dict[str, list[str]] = field(default_factory=dict)
    external_ids: dict[tuple[str, str], str] = field(default_factory=dict)
    revision_heads: dict[str, str] = field(default_factory=dict)
    revision_labels: dict[str, str] = field(default_factory=dict)
    revision_counts: dict[str, int] = field(default_factory=dict)
    statement_heads: dict[str, str] = field(default_factory=dict)
    active_snapshot: str | None = None
    applied: int = 0

    # AliasRegistryView -----------------------------------------------------

    def alias_record(self, alias: str) -> AliasRecord | None:
        return self.aliases.get(alias)

    def counter_value(self, key: str) -> int:
        return self.counters.get(key, 0)

    def live_alias_of(self, entity_id: str) -> str | None:
        for alias in self.entity_aliases.get(entity_id, ()):
            if self.aliases[alias].state != "abandoned":
                return alias
        return None

    # Checks used before appending -----------------------------------------

    def next_revision_label(self, contribution_id: str, expected_predecessor: str | None) -> str:
        head = self.revision_heads.get(contribution_id)
        if head != expected_predecessor:
            raise StalePredecessor(contribution_id, expected_predecessor, head)
        return f"r{self.revision_counts.get(contribution_id, 0) + 1}"

    def check_statement_advance(self, problem_id: str, expected_predecessor: str | None) -> None:
        head = self.statement_heads.get(problem_id)
        if head != expected_predecessor:
            raise StalePredecessor(problem_id, expected_predecessor, head)

    # Event application -----------------------------------------------------

    def apply(self, event: Mapping[str, Any]) -> None:
        handler = getattr(self, f"_apply_{event['type']}", None)
        if handler is not None:
            handler(event["payload"], event["event_id"])
        self.applied += 1

    def _apply_alias_reserved(self, p: Mapping[str, Any], event_id: str) -> None:
        if p["alias"] in self.aliases:
            raise LedgerCorruption(f"{p['alias']} reserved twice")
        if self.live_alias_of(p["entity_id"]) is not None:
            raise LedgerCorruption(f"{p['entity_id']} already has a live alias")
        self.aliases[p["alias"]] = AliasRecord(
            alias=p["alias"],
            entity_id=p["entity_id"],
            scheme_id=p["scheme_id"],
            allocation_authority=p["allocation_authority"],
            parent_alias=p["parent_alias"],
            counter_key=p["counter_key"],
            sequence=p["sequence"],
            external_identifier=p["external_identifier"],
            state="reserved",
            reserved_by=event_id,
        )
        self.entity_aliases.setdefault(p["entity_id"], []).append(p["alias"])
        if p["counter_key"] is not None:
            self.counters[p["counter_key"]] = max(self.counters.get(p["counter_key"], 0), p["sequence"])

    def _transition(self, p: Mapping[str, Any], new_state: str) -> None:
        record = self.aliases.get(p["alias"])
        if record is None or record.entity_id != p["entity_id"] or record.state != "reserved":
            raise LedgerCorruption(f"cannot mark {p['alias']} {new_state}")
        self.aliases[p["alias"]] = dataclasses.replace(record, state=new_state)

    def _apply_alias_bound(self, p: Mapping[str, Any], event_id: str) -> None:
        self._transition(p, "bound")

    def _apply_alias_abandoned(self, p: Mapping[str, Any], event_id: str) -> None:
        self._transition(p, "abandoned")

    def _apply_external_id_mapped(self, p: Mapping[str, Any], event_id: str) -> None:
        key = (p["scheme"], p["identifier"])
        if self.external_ids.get(key, p["entity_id"]) != p["entity_id"]:
            raise LedgerCorruption(f"{key} mapped to two entities")
        self.external_ids[key] = p["entity_id"]

    def _apply_statement_revised(self, p: Mapping[str, Any], event_id: str) -> None:
        if self.statement_heads.get(p["problem_id"]) != p["predecessor"]:
            raise LedgerCorruption(f"statement revision {p['statement_revision_id']} does not extend the head")
        self.statement_heads[p["problem_id"]] = p["statement_revision_id"]

    def _apply_revision_accepted(self, p: Mapping[str, Any], event_id: str) -> None:
        try:
            label = self.next_revision_label(p["contribution_id"], p["predecessor"])
        except StalePredecessor as exc:
            raise LedgerCorruption(str(exc)) from exc
        if p["sequence_label"] != label or p["revision_id"] in self.revision_labels:
            raise LedgerCorruption(f"revision {p['revision_id']} has label {p['sequence_label']}, expected {label}")
        self.revision_heads[p["contribution_id"]] = p["revision_id"]
        self.revision_labels[p["revision_id"]] = label
        self.revision_counts[p["contribution_id"]] = self.revision_counts.get(p["contribution_id"], 0) + 1

    def _apply_snapshot_activated(self, p: Mapping[str, Any], event_id: str) -> None:
        if p["previous_snapshot_id"] != self.active_snapshot:
            raise LedgerCorruption(f"snapshot {p['snapshot_id']} does not replace the active snapshot")
        self.active_snapshot = p["snapshot_id"]

    def summary(self) -> dict[str, Any]:
        """A canonical-JSON-ready view, for comparing rebuilds."""
        return {
            "aliases": {a: dataclasses.asdict(r) for a, r in sorted(self.aliases.items())},
            "counters": dict(sorted(self.counters.items())),
            "external_ids": {f"{s}:{i}": e for (s, i), e in sorted(self.external_ids.items())},
            "revision_heads": dict(sorted(self.revision_heads.items())),
            "revision_labels": dict(sorted(self.revision_labels.items())),
            "statement_heads": dict(sorted(self.statement_heads.items())),
            "active_snapshot": self.active_snapshot,
            "applied": self.applied,
        }


def rebuild(events: Iterable[Mapping[str, Any]]) -> LedgerState:
    state = LedgerState()
    for event in events:
        state.apply(event)
    return state
