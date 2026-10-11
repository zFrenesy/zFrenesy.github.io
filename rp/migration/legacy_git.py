"""Read the legacy repository through Git objects at the pinned commit.

Never reads or writes the working tree: a clone with local edits, untracked
files or a different checkout still yields exactly the pinned content.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from rp.timeutil import format_instant

__all__ = ["LEGACY_COMMIT", "LegacyRepo", "TreeEntry"]

LEGACY_COMMIT = "b1f633121074e16579fa7fd05314e5f504d29bae"


@dataclass(frozen=True, slots=True)
class TreeEntry:
    path: str
    mode: str
    sha: str
    size: int


class LegacyRepo:
    def __init__(self, path: str | Path, commit: str = LEGACY_COMMIT):
        self.path = Path(path)
        self.commit = commit
        kind = self._git("cat-file", "-t", commit).decode().strip()
        if kind != "commit":
            raise ValueError(f"{commit} is not a commit in {self.path}")

    def _git(self, *args: str, stdin: bytes | None = None, check: bool = True) -> bytes:
        proc = subprocess.run(
            ["git", "-C", str(self.path), "-c", "core.quotePath=false", *args],
            input=stdin,
            capture_output=True,
            check=False,
        )
        if check and proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(args[:3])} failed: {proc.stderr.decode(errors='replace')[:300]}")
        return proc.stdout

    def tree(self, prefix: str = "") -> list[TreeEntry]:
        """Every blob at the pinned commit (optionally under ``prefix``), sorted by path."""
        args = ["ls-tree", "-r", "-z", "-l", self.commit]
        if prefix:
            args += ["--", prefix]
        entries = []
        for record in self._git(*args).split(b"\0"):
            if not record:
                continue
            meta, path = record.split(b"\t", 1)
            mode, kind, sha, size = meta.split()
            if kind != b"blob":
                entries.append(TreeEntry(path.decode("utf-8"), mode.decode(), sha.decode(), -1))
                continue
            entries.append(TreeEntry(path.decode("utf-8"), mode.decode(), sha.decode(), int(size)))
        return sorted(entries, key=lambda e: e.path)

    def blobs(self, shas: Iterable[str]) -> dict[str, bytes]:
        wanted = list(dict.fromkeys(shas))
        if not wanted:
            return {}
        out = self._git("cat-file", "--batch", stdin="".join(f"{s}\n" for s in wanted).encode())
        result: dict[str, bytes] = {}
        cursor = 0
        for sha in wanted:
            newline = out.index(b"\n", cursor)
            header = out[cursor:newline].split()
            if len(header) < 3 or header[1] == b"missing":
                raise KeyError(f"blob {sha} is missing")
            size = int(header[2])
            result[sha] = out[newline + 1 : newline + 1 + size]
            cursor = newline + 1 + size + 1
        return result

    def read_at(self, commit: str, path: str) -> bytes | None:
        proc = subprocess.run(
            ["git", "-C", str(self.path), "cat-file", "blob", f"{commit}:{path}"],
            capture_output=True,
            check=False,
        )
        return proc.stdout if proc.returncode == 0 else None

    def blob_at(self, commit: str, path: str) -> str | None:
        out = self._git("rev-parse", "--verify", "--quiet", f"{commit}:{path}", check=False).decode().strip()
        return out or None

    def path_log(self, path: str) -> list[tuple[str, str]]:
        """(commit, author instant) for every commit touching ``path``, oldest first."""
        out = self._git("log", "--format=%H%x09%aI", self.commit, "--", path).decode()
        rows = [line.split("\t") for line in out.splitlines() if line]
        return [(c, _utc(d)) for c, d in reversed(rows)]

    def paths_ever(self, prefix: str) -> list[str]:
        out = self._git("log", "--format=", "--name-only", "-z", self.commit, "--", prefix).decode("utf-8")
        return sorted({p.strip("\n") for p in out.split("\0") if p.strip("\n")})

    def first_added(self, prefix: str = "attacks") -> dict[str, str]:
        """Earliest author instant at which each path was added (no rename detection), as UTC."""
        out = self._git("log", "--no-renames", "--diff-filter=A", "--format=POSTED:%aI", "--name-only", self.commit, "--", prefix).decode(
            "utf-8"
        )
        dates: dict[str, str] = {}
        current = None
        for line in out.splitlines():
            if line.startswith("POSTED:"):
                current = _utc(line[7:])
            elif line and current:
                dates[line] = min(current, dates.get(line, current))
        return dates


def _utc(iso: str) -> str:
    return format_instant(datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(UTC))
