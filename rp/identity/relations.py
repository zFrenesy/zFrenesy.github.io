"""Typed problem relations (§3, §15).

One primary hierarchical parent per problem, an acyclic ``subproblem_of``
relation, and additional typed edges. Relations describe structure only:
nothing here reads or propagates any status, and reparenting changes edges,
never identity or aliases.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from rp.vocab import RELATION_TYPES

__all__ = ["Relation", "RelationIssue", "check_relations", "relations_from_problem", "subproblem_children"]


@dataclass(frozen=True, slots=True)
class Relation:
    source: str
    type: str
    target: str
    primary: bool = False


@dataclass(frozen=True, slots=True)
class RelationIssue:
    code: str
    message: str
    source: str
    target: str | None = None


def relations_from_problem(problem: Mapping[str, Any]) -> list[Relation]:
    source = problem["problem_id"]
    return [
        Relation(source, rel["type"], rel["target_problem_id"], bool(rel.get("primary", False)))
        for rel in problem.get("relations", [])
    ]


def check_relations(relations: Iterable[Relation], known_problems: set[str] | None = None) -> list[RelationIssue]:
    issues: list[RelationIssue] = []
    seen: set[tuple[str, str, str]] = set()
    primary_parents: dict[str, list[str]] = defaultdict(list)
    parents: dict[str, set[str]] = defaultdict(set)
    for rel in relations:
        if rel.type not in RELATION_TYPES:
            issues.append(RelationIssue("relation.unknown_type", f"unknown relation type {rel.type!r}", rel.source, rel.target))
            continue
        if rel.source == rel.target:
            issues.append(RelationIssue("relation.self", f"{rel.source} cannot relate to itself", rel.source, rel.target))
            continue
        key = (rel.source, rel.type, rel.target)
        if key in seen:
            issues.append(RelationIssue("relation.duplicate", f"duplicate {rel.type} relation", rel.source, rel.target))
            continue
        seen.add(key)
        if known_problems is not None and rel.target not in known_problems:
            issues.append(RelationIssue("relation.unknown_target", f"{rel.target} is not a known problem", rel.source, rel.target))
        if rel.primary and rel.type != "subproblem_of":
            issues.append(
                RelationIssue("relation.primary_misuse", "only subproblem_of relations can be primary", rel.source, rel.target)
            )
        if rel.type == "subproblem_of":
            parents[rel.source].add(rel.target)
            if rel.primary:
                primary_parents[rel.source].append(rel.target)
    for source, targets in sorted(primary_parents.items()):
        if len(targets) > 1:
            issues.append(
                RelationIssue("relation.multiple_primary_parents", f"{source} has {len(targets)} primary parents", source)
            )
    for source in sorted(parents):
        if source not in primary_parents:
            issues.append(RelationIssue("relation.no_primary_parent", f"{source} has subproblem_of edges but no primary parent", source))
    issues.extend(_cycles(parents))
    return issues


def _cycles(parents: Mapping[str, set[str]]) -> list[RelationIssue]:
    """Report each subproblem_of cycle once (iterative depth-first search)."""
    white, grey, black = 0, 1, 2
    colour: dict[str, int] = defaultdict(int)
    issues = []
    for start in sorted(parents):
        if colour[start] != white:
            continue
        stack = [(start, iter(sorted(parents.get(start, ()))))]
        path = [start]
        colour[start] = grey
        while stack:
            node, children = stack[-1]
            child = next(children, None)
            if child is None:
                colour[node] = black
                stack.pop()
                path.pop()
            elif colour[child] == grey:
                cycle = path[path.index(child):] + [child]
                issues.append(RelationIssue("relation.cycle", "subproblem_of cycle: " + " -> ".join(cycle), child))
            elif colour[child] == white:
                colour[child] = grey
                path.append(child)
                stack.append((child, iter(sorted(parents.get(child, ())))))
    return issues


def subproblem_children(relations: Iterable[Relation]) -> dict[str, list[str]]:
    """Primary parent -> children, for rendering the subproblem tree."""
    children: dict[str, list[str]] = defaultdict(list)
    for rel in relations:
        if rel.type == "subproblem_of" and rel.primary:
            children[rel.target].append(rel.source)
    return {parent: sorted(kids) for parent, kids in sorted(children.items())}
