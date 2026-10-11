"""Classify every file of the legacy repository at the pinned commit (docs/adr/0010).

Every blob gets exactly one class. Research files under ``attacks/`` map to
problems and contributions; ``reviews/`` and ``lists/`` are inputs; everything
else (site code, generated pages, scripts) is ``non_research`` and is not
migrated, but is still counted so nothing is silently skipped.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from rp.migration.headers import Headers, parse_headers
from rp.migration.legacy_git import LegacyRepo

__all__ = ["CLASSES", "Inventory", "InventoryEntry", "build_inventory"]

CLASSES = (
    "statement",
    "attempt",
    "reused_writeup",
    "statement_copy",
    "external_claim_summary",
    "human_contribution",
    "import_note",
    "review",
    "catalogue_list",
    "non_research",
    "unclassified",
)
COLLECTION_KEYS = {"erdos": "erdos", "economics": "economics", "top_problems": "top", "mo": "mo"}
_NUMBERED = re.compile(r"([1-9][0-9]*)(?:_v([1-9][0-9]*))?\.tex")
_ODD_NUMBERED = re.compile(r"([1-9][0-9]*)_([1-9][0-9]*)\.tex")
_ECONOMICS = re.compile(r"([A-Z][0-9]{2}-[1-9][0-9]*)(?:_v([1-9][0-9]*))?\.tex")
_MO = re.compile(r"([1-9][0-9]*)[ -].*\.tex")


@dataclass
class InventoryEntry:
    path: str
    blob: str
    mode: str
    size: int
    cls: str
    collection: str | None = None
    folder: str | None = None
    problem_key: str | None = None
    version: int | None = None
    headers: Headers | None = None
    uncertainty: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"path": self.path, "blob": self.blob, "class": self.cls, "size": self.size}
        for key in ("collection", "folder", "problem_key", "version"):
            if getattr(self, key) is not None:
                out[key] = getattr(self, key)
        if self.headers is not None and self.headers.values:
            out["headers"] = sorted(self.headers.values)
        if self.uncertainty:
            out["uncertainty"] = self.uncertainty
        return out


@dataclass
class Inventory:
    commit: str
    entries: list[InventoryEntry]
    contents: dict[str, bytes]  # blob sha -> bytes, for research files only

    def by_class(self, cls: str) -> list[InventoryEntry]:
        return [e for e in self.entries if e.cls == cls]

    def counts(self) -> dict[str, int]:
        return dict(sorted(Counter(e.cls for e in self.entries).items()))

    def text(self, entry: InventoryEntry) -> str:
        return self.contents[entry.blob].decode("utf-8")

    def as_json(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "source_commit": self.commit,
            "counts": self.counts(),
            "attacks_files": sum(1 for e in self.entries if e.path.startswith("attacks/")),
            "entries": [e.as_json() for e in self.entries if e.cls != "non_research"],
            "non_research_files": sum(1 for e in self.entries if e.cls == "non_research"),
        }

    def report(self) -> str:
        lines = [
            f"# Legacy inventory at {self.commit[:12]}",
            "",
            f"{len(self.entries)} files in the commit; {sum(1 for e in self.entries if e.path.startswith('attacks/'))} under `attacks/`.",
            "",
            "| Class | Files |",
            "| --- | --- |",
        ]
        lines += [f"| {cls} | {n} |" for cls, n in self.counts().items()]
        uncertain = [e for e in self.entries if e.uncertainty]
        lines += ["", f"## Needs owner review ({len(uncertain)})", ""]
        lines += [f"- `{e.path}`: {'; '.join(e.uncertainty)}" for e in uncertain]
        return "\n".join(lines) + "\n"


def _classify(entry: InventoryEntry, text: str | None) -> None:
    parts = entry.path.split("/")
    if parts[0] == "reviews":
        entry.cls = "review" if entry.path.endswith(".json") else "non_research"
        return
    if parts[0] == "lists":
        entry.cls = "catalogue_list"
        return
    if parts[0] != "attacks":
        entry.cls = "non_research"
        return
    if len(parts) != 5 or parts[1] != "open_problems" or parts[2] not in COLLECTION_KEYS:
        entry.cls = "unclassified"
        entry.uncertainty.append("path outside the known attacks/open_problems/<collection>/<folder>/ layout")
        return
    collection, folder, name = parts[2], parts[3], parts[4]
    entry.collection, entry.folder = COLLECTION_KEYS[collection], folder
    if not name.endswith(".tex"):
        entry.cls = "import_note"
        return
    headers = parse_headers(text or "")
    entry.headers = headers
    # Merged Economics statements keep every source formulation's identity comment;
    # their identity comes from lists/economics/problems.json, not from these headers.
    entry.uncertainty.extend(
        issue for issue in headers.issues
        if not (folder == "statements" and issue.startswith("ECONOMICS_PROBLEM appears"))
    )
    if collection == "economics":
        match = _ECONOMICS.fullmatch(name)
        if match:
            entry.problem_key, entry.version = f"economics:{match[1]}", int(match[2] or 1)
        entry.cls = "statement" if folder == "statements" else "attempt"
    elif collection == "mo":
        match = _MO.fullmatch(name)
        if match:
            entry.problem_key, entry.version = f"mo:{match[1]}", 1
        entry.cls = "attempt"
    else:
        match = _NUMBERED.fullmatch(name)
        if match:
            entry.problem_key, entry.version = f"{entry.collection}:{match[1]}", int(match[2] or 1)
        else:
            odd = _ODD_NUMBERED.fullmatch(name)
            if odd:
                entry.problem_key, entry.version = f"{entry.collection}:{odd[1]}", None
                entry.uncertainty.append("filename is outside the legacy NAME[_vK].tex pattern and was not shown on the legacy site")
        if collection == "top_problems" and folder == "definitions":
            entry.cls = "statement"
        elif collection == "top_problems" and folder == "openai":
            entry.cls = "external_claim_summary"
        elif collection == "top_problems" and folder == "Human_Contribution":
            entry.cls = "human_contribution"
        elif "COLLECTION_METADATA" in headers.data and headers.data["COLLECTION_METADATA"].get("kind") == "reused_writeup":
            entry.cls = "reused_writeup"
        elif headers.entry_kind == "statement_only":
            entry.cls = "statement_copy"
            entry.uncertainty.append("statement-only file inside a model folder; kept as a record without a claim")
        else:
            entry.cls = "attempt"
    if entry.problem_key is None:
        entry.uncertainty.append("cannot determine the problem from the filename")


def build_inventory(repo: LegacyRepo) -> Inventory:
    tree = [e for e in repo.tree() if e.size >= 0]
    research = [e for e in tree if e.path.startswith(("attacks/", "reviews/", "lists/"))]
    contents = repo.blobs(e.sha for e in research)
    entries = []
    for item in tree:
        entry = InventoryEntry(item.path, item.sha, item.mode, item.size, "unclassified")
        text = contents.get(item.sha, b"").decode("utf-8") if item.path.endswith(".tex") else None
        _classify(entry, text)
        if entry.mode not in ("100644", "100755"):
            entry.uncertainty.append(f"mode {entry.mode}")
        entries.append(entry)
    return Inventory(repo.commit, entries, contents)
