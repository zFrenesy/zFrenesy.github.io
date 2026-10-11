"""Generated, non-authoritative browse indexes for the research tree (spec §3).

``browse/aliases.json`` maps human handles to folders so contributor tools can find
a problem from its alias without the ledger branch. The ledger stays authoritative;
these files are regenerated with every managed publication.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass

__all__ = ["BrowseContribution", "BrowseProblem", "render_index", "render_readme"]


@dataclass(frozen=True)
class BrowseProblem:
    alias: str
    problem_id: str
    statement_revision_id: str
    title: str
    path: str


@dataclass(frozen=True)
class BrowseContribution:
    alias: str
    contribution_id: str
    revision_id: str
    home: str
    title: str
    path: str


def render_index(problems: Iterable[BrowseProblem], contributions: Iterable[BrowseContribution]) -> bytes:
    data = {
        "schema_version": 1,
        "note": "Generated index of human handles. Not authoritative: the automation-ledger branch is.",
        "problems": {p.alias: {"id": p.problem_id, "statement_revision_id": p.statement_revision_id, "title": p.title, "path": p.path}
                     for p in sorted(problems, key=lambda p: p.alias)},
        "contributions": {c.alias: {"id": c.contribution_id, "revision_id": c.revision_id, "home": c.home, "title": c.title, "path": c.path}
                          for c in sorted(contributions, key=lambda c: c.alias)},
    }
    return (json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def render_readme(problems: Iterable[BrowseProblem]) -> bytes:
    lines = [
        "# Problems by handle",
        "",
        "Generated index; the folders hold the records. Use `rp start <HANDLE>` to begin work on a problem.",
        "",
        "| Handle | Problem | Folder |",
        "| --- | --- | --- |",
    ]
    for p in sorted(problems, key=lambda p: p.alias):
        title = p.title.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {p.alias} | {title} | [{p.path}](../{p.path}/) |")
    return ("\n".join(lines) + "\n").encode("utf-8")
