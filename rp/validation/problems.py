"""Admission checks for contributed problems and Tier 1 duplicate screening (spec §15).

The schema already requires the kind-specific blocks (``citation``, ``proposal``,
``derivation``); this module adds what needs the statement text or the research
tree. Duplicate screening never rejects: it returns the closest existing statements
so the contributor can explain the difference or link the problem as a variant.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rp import strict_yaml
from rp.catalog import Catalog, default_catalog
from rp.identity.paths import problem_dir
from rp.strict_yaml import StrictYamlError

__all__ = ["Similar", "admission_issues", "isbn_valid", "shingles", "similar_statements"]

MIN_STATEMENT_CHARS = 40
SHINGLE = 3
DUPLICATE_THRESHOLD = 0.2
DUPLICATE_LIMIT = 5
CONTRIBUTED_KINDS = ("literature", "proposed", "derived")

_TEX_COMMENT = re.compile(r"(?<!\\)%.*")
_TEX_COMMAND = re.compile(r"\\[A-Za-z]+\*?")
_WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Similar:
    problem_id: str
    title: str
    path: str
    score: float


def isbn_valid(value: str) -> bool:
    if len(value) == 13 and value.isdigit():
        return sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(value)) % 10 == 0
    if len(value) == 10 and value[:9].isdigit() and (value[9].isdigit() or value[9] == "X"):
        digits = [int(d) for d in value[:9]] + [10 if value[9] == "X" else int(value[9])]
        return sum((10 - i) * d for i, d in enumerate(digits)) % 11 == 0
    return False


def _plain(text: str) -> str:
    text = _TEX_COMMENT.sub(" ", text)
    text = _TEX_COMMAND.sub(" ", text)
    return text.lower()


def shingles(text: str) -> frozenset[tuple[str, ...]]:
    words = _WORD.findall(_plain(text))
    if len(words) < SHINGLE:
        return frozenset({tuple(words)}) if words else frozenset()
    return frozenset(tuple(words[i:i + SHINGLE]) for i in range(len(words) - SHINGLE + 1))


def _primary(record: Mapping[str, Any]) -> str | None:
    return next((d["discipline"] for d in record.get("disciplines", []) if d.get("role") == "primary"), None)


@functools.lru_cache(maxsize=4)
def _index(root: str, discipline: str | None, stamp: tuple[int, int]) -> tuple[tuple[str, str, str, frozenset], ...]:
    """(problem_id, title, folder, shingles) for every statement in a discipline. Cached per tree listing."""
    entries = []
    base = Path(root)
    for problem_yaml in sorted(base.glob("problems/*/*/problem.yaml")):
        try:
            record = strict_yaml.load(problem_yaml.read_bytes())
        except (StrictYamlError, OSError):
            continue
        if discipline and _primary(record) != discipline:
            continue
        name = record.get("statement_artifact", {}).get("path", "")
        statement = problem_yaml.parent / name
        if name and statement.is_file() and not statement.is_symlink():
            words = shingles(statement.read_text(encoding="utf-8", errors="replace"))
            if words:
                entries.append((record["problem_id"], record.get("title", ""), problem_yaml.parent.relative_to(base).as_posix(), words))
    return tuple(entries)


def _stamp(root: Path) -> tuple[int, int]:
    listing = sorted(str(p) for p in root.glob("problems/*/*/problem.yaml"))
    return len(listing), hash("\n".join(listing))


def similar_statements(text: str, discipline: str | None, root: Path, *, exclude: str | None = None,
                       limit: int = DUPLICATE_LIMIT, threshold: float = DUPLICATE_THRESHOLD) -> list[Similar]:
    """The existing statements in the same discipline that overlap most with ``text`` (Jaccard on word shingles)."""
    mine = shingles(text)
    if not mine:
        return []
    found = []
    for problem_id, title, path, theirs in _index(str(Path(root).resolve()), discipline, _stamp(Path(root))):
        if problem_id == exclude:
            continue
        score = len(mine & theirs) / len(mine | theirs)
        if score >= threshold:
            found.append(Similar(problem_id, title, path, round(score, 3)))
    return sorted(found, key=lambda s: (-s.score, s.problem_id))[:limit]


def admission_issues(record: Mapping[str, Any], statement: str | None, *, root: Path | None = None,
                     catalog: Catalog | None = None) -> list[tuple[str, str]]:
    """(severity, message) pairs for a contributed problem. Schema validation runs separately."""
    catalog = catalog or default_catalog()
    issues: list[tuple[str, str]] = []
    kind = record.get("kind")
    if kind not in CONTRIBUTED_KINDS:
        return [("error", "contributors may add literature, proposed or derived problems only")]
    body = re.sub(r"^#.*$", "", statement or "", flags=re.MULTILINE)
    if len(re.sub(r"\s+", "", body)) < MIN_STATEMENT_CHARS:
        issues.append(("error", "the statement is too short to be well posed; state it precisely with its definitions"))
    primary = _primary(record)
    config = catalog.disciplines.get(primary or "")
    if config and config["classification"] and not record.get("classifications"):
        # A subproblem inherits its parent's classification, which imported problems may lack.
        issues.append(("warning" if kind == "derived" else "error", f"add at least one {config['classification']['name']} code"))
    if kind == "literature":
        reference = record.get("citation", {}).get("reference", {})
        if reference.get("kind") == "isbn" and not isbn_valid(reference.get("value", "")):
            issues.append(("error", "the ISBN check digit is wrong"))
        issues.append(("warning", "the citation is shown as 'citation not independently checked'"))
    if kind == "derived" and root is not None:
        parent = record.get("derivation", {}).get("parent_problem_id")
        if parent and not (root / problem_dir(parent) / "problem.yaml").is_file():
            issues.append(("error", f"the parent problem {parent} does not exist"))
    if kind in ("proposed", "derived"):
        issues.append(("warning", "listed under proposed questions: 'Proposed by a contributor. Not established as open or novel.'"))
    return issues
