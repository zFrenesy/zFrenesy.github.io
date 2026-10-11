"""Trusted catalogue presentation metadata, separate from permanent identities.

Economics ranks and JEL names are build inputs from the platform repository;
research records cannot change catalogue ordering by declaring a rank.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Mapping

if TYPE_CHECKING:
    from rp.site.model import Problem

CATALOGUES = Path(__file__).resolve().parents[2] / "site" / "catalogues"
ECONOMICS_RANKINGS = CATALOGUES / "economics-rankings.csv"
ECONOMICS_JEL = CATALOGUES / "economics-jel.json"
_ECONOMICS_ID = re.compile(r"[A-Z][0-9]{2}-[1-9][0-9]*")
_JEL_CODE = re.compile(r"[A-Z][0-9]{0,2}")


def load_economics_rankings(path: Path | None = None) -> dict[str, int]:
    """Read an editable, complete rank order keyed by permanent ECON aliases.

    Rows use the original catalogue's stable Problem ID, never its reused OP
    source ID or current rank. Reject ties, gaps and duplicates before building
    any pages. A new catalogue entry may remain unranked until explicitly added.
    """
    path = ECONOMICS_RANKINGS if path is None else Path(path)
    ranks: dict[str, int] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        if len(headers) != len(set(headers)) or not {"Problem ID", "New rank"} <= set(headers):
            raise ValueError("Economics ranking CSV requires unique Problem ID and New rank columns")
        for line, row in enumerate(reader, 2):
            identifier = (row.get("Problem ID") or "").strip()
            value = (row.get("New rank") or "").strip()
            if None in row or not _ECONOMICS_ID.fullmatch(identifier):
                raise ValueError(f"Economics ranking row {line}: invalid permanent Problem ID")
            if not re.fullmatch(r"[1-9][0-9]*", value):
                raise ValueError(f"Economics ranking row {line}: New rank must be a positive integer")
            alias = f"ECON-{identifier}"
            if alias in ranks:
                raise ValueError(f"Economics ranking row {line}: duplicate Problem ID {identifier}")
            jel = (row.get("JEL code") or "").strip()
            if jel and jel != identifier.split("-", 1)[0]:
                raise ValueError(f"Economics ranking row {line}: JEL code does not match Problem ID")
            ranks[alias] = int(value)
    if not ranks or set(ranks.values()) != set(range(1, len(ranks) + 1)):
        raise ValueError("Economics ranks must be unique and contiguous from 1 to the number of entries")
    return ranks


def load_economics_jel_labels(path: Path | None = None) -> dict[str, str]:
    """Load the pinned classification names, including parent categories."""
    path = ECONOMICS_JEL if path is None else Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    labels = data.get("labels") if isinstance(data, dict) else None
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(labels, dict) or not labels:
        raise ValueError("Unsupported Economics JEL classification format")
    if any(not isinstance(code, str) or not _JEL_CODE.fullmatch(code)
           or not isinstance(label, str) or not label.strip() for code, label in labels.items()):
        raise ValueError("Economics JEL classification requires valid codes and non-empty names")
    return labels


def catalogue_rank(problem: Problem, ranks: Mapping[str, int]) -> int | None:
    """Look up display rank without changing source records or interpreting IDs."""
    return ranks.get(problem.alias) if problem.collection == "economics" else None


def catalogue_sort_key(problem: Problem, ranks: Mapping[str, int]) -> tuple[bool, int, str]:
    """Ranked entries first, then unranked entries in stable alias order."""
    rank = catalogue_rank(problem, ranks)
    return rank is None, rank or 0, problem.alias


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the trusted Economics catalogue display configuration.")
    parser.add_argument("--rankings", type=Path, default=ECONOMICS_RANKINGS)
    parser.add_argument("--jel", type=Path, default=ECONOMICS_JEL)
    args = parser.parse_args()
    ranks = load_economics_rankings(args.rankings)
    labels = load_economics_jel_labels(args.jel)
    missing = sorted({alias.split("-")[1] for alias in ranks} - set(labels))
    if missing:
        raise ValueError("Missing Economics JEL descriptions: " + ", ".join(missing))
    print(f"Validated {len(ranks)} Economics ranks and {len(labels)} JEL names.")


if __name__ == "__main__":
    main()
