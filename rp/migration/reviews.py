"""Recover every historical state of the legacy review files (spec §12).

The legacy converter overwrote one JSON file per problem, so earlier reviews
survive only in Git history. Each path's states are read from every commit
that touched it; a deletion is recorded as such, never dropped.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from rp.migration.legacy_git import LegacyRepo

__all__ = ["ReviewHistory", "ReviewVersion", "review_history"]

_PATH = re.compile(r"reviews/(erdos|open_problems|mo)/([0-9]+)\.json")


@dataclass(frozen=True)
class ReviewVersion:
    commit: str
    author_date: str
    blob: str | None
    data: dict[str, Any] | None  # None: the file was deleted at this commit

    @property
    def issue_number(self) -> int | None:
        value = (self.data or {}).get("issue_number")
        return int(value) if value not in (None, "") and str(value).isdigit() else None

    def logins(self) -> set[str]:
        data = self.data or {}
        found: set[str] = set()
        reviewed = data.get("reviewed_by")
        for value in [reviewed] if isinstance(reviewed, str) else reviewed or []:
            found.update(x.lstrip("@") for x in str(value).replace(",", " ").split())
        for value in data.get("submitted_by") or []:
            found.add(str(value).lstrip("@"))
        return {login for login in found if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", login)}


@dataclass
class ReviewHistory:
    path: str
    collection: str
    problem_id: str
    versions: list[ReviewVersion] = field(default_factory=list)

    @property
    def deleted(self) -> bool:
        return bool(self.versions) and self.versions[-1].data is None

    @property
    def current(self) -> ReviewVersion | None:
        live = [v for v in self.versions if v.data is not None]
        return live[-1] if live else None


def review_history(repo: LegacyRepo) -> dict[str, ReviewHistory]:
    histories: dict[str, ReviewHistory] = {}
    for path in repo.paths_ever("reviews"):
        match = _PATH.fullmatch(path)
        if not match:
            continue
        history = ReviewHistory(path, match.group(1), match.group(2))
        previous_blob: str | None = "start"
        for commit, date in repo.path_log(path):
            blob = repo.blob_at(commit, path)
            if blob == previous_blob:
                continue
            previous_blob = blob
            data = None
            if blob is not None:
                raw = repo.read_at(commit, path)
                data = json.loads(raw.decode("utf-8")) if raw is not None else None
            history.versions.append(ReviewVersion(commit, date, blob, data))
        histories[path] = history
    return dict(sorted(histories.items()))
