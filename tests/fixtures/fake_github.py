"""An in-memory GitHub for intake tests, backed by a real Git repository for refs and commits."""

from __future__ import annotations

import itertools
import os
import subprocess
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path

from rp.intake.snapshot import Actor, ChangedFile, Comment, IntakeSnapshot

APP_ID = 777
BOT = Actor("we-solve-intake[bot]", 9000)
BOT_ENV = {"GIT_AUTHOR_NAME": "we-solve-intake[bot]", "GIT_AUTHOR_EMAIL": "intake@example.invalid",
           "GIT_COMMITTER_NAME": "we-solve-intake[bot]", "GIT_COMMITTER_EMAIL": "intake@example.invalid",
           "GIT_AUTHOR_DATE": "2026-10-12T00:00:00Z", "GIT_COMMITTER_DATE": "2026-10-12T00:00:00Z"}


def git(root: Path, *args: str, env: dict | None = None, data: bytes | None = None) -> str:
    proc = subprocess.run(["git", "-C", str(root), *args], input=data, capture_output=True, check=True,
                          env={**os.environ, **BOT_ENV, **(env or {})})
    return proc.stdout.decode().strip()


@dataclass
class Item:
    number: int
    kind: str
    author: Actor
    title: str
    body: str
    state: str = "open"
    labels: list[str] = field(default_factory=list)
    comments: list[Comment] = field(default_factory=list)
    head: str | None = None  # pull requests: branch name
    state_reason: str | None = None


class FakeGitHub:
    def __init__(self, repo: Path, repository: str = "we-solve-staging/research"):
        self.repo, self.repository = repo, repository
        self.items: dict[int, Item] = {}
        self._numbers = itertools.count(1)
        self._comment_ids = itertools.count(100)
        self.calls: list[tuple] = []

    # test helpers -------------------------------------------------------------
    def open_issue(self, author: Actor, title: str, body: str, labels=()) -> int:
        number = next(self._numbers)
        self.items[number] = Item(number, "issue", author, title, body, labels=list(labels))
        return number

    def comment_as(self, number: int, author: Actor, body: str, at: str, app_id: int | None = None) -> int:
        cid = next(self._comment_ids)
        self.items[number].comments.append(Comment(cid, author, body, at, app_id))
        return cid

    def snapshot(self, number: int, created_at="2026-10-12T00:00:00Z", **extra) -> IntakeSnapshot:
        item = self.items[number]
        return IntakeSnapshot(self.repository, item.kind, number, item.state, item.author, item.title, item.body, created_at,
                              tuple(item.labels), tuple(item.comments), **extra)

    # GitHubPort ---------------------------------------------------------------
    def comments(self, number: int) -> list[Comment]:
        return list(self.items[number].comments)

    def create_comment(self, number: int, body: str) -> int:
        self.calls.append(("comment", number))
        return self.comment_as(number, BOT, body, "2026-10-12T00:00:00Z", APP_ID)

    def update_comment(self, comment_id: int, body: str) -> None:
        self.calls.append(("update_comment", comment_id))
        for item in self.items.values():
            item.comments = [replace(c, body=body) if c.id == comment_id else c for c in item.comments]

    def set_labels(self, number: int, add: list[str], remove: list[str]) -> None:
        item = self.items[number]
        item.labels = [label for label in item.labels if label not in remove] + [label for label in add if label not in item.labels]

    def set_state(self, number: int, state: str, reason: str | None = None) -> None:
        self.calls.append(("state", number, state))
        self.items[number].state, self.items[number].state_reason = state, reason

    def branch_sha(self, branch: str) -> str | None:
        proc = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], capture_output=True, text=True)
        return proc.stdout.strip() or None

    def set_branch(self, branch: str, sha: str) -> None:
        self.calls.append(("set_branch", branch, sha))
        git(self.repo, "update-ref", f"refs/heads/{branch}", sha)

    def commit_files(self, parent: str, files: dict[str, bytes], message: str) -> str:
        self.calls.append(("commit", parent))
        with tempfile.TemporaryDirectory() as tmp:
            env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
            git(self.repo, "read-tree", parent, env=env)
            for path, content in files.items():
                blob = git(self.repo, "hash-object", "-w", "--stdin", data=content)
                git(self.repo, "update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", env=env)
            tree = git(self.repo, "write-tree", env=env)
        return git(self.repo, "commit-tree", tree, "-p", parent, "-m", message)

    def tree_matches(self, sha: str, files: dict[str, bytes]) -> bool:
        for path, content in files.items():
            proc = subprocess.run(["git", "-C", str(self.repo), "cat-file", "blob", f"{sha}:{path}"], capture_output=True)
            if proc.returncode != 0 or proc.stdout != content:
                return False
        return True

    def find_pull(self, branch: str) -> int | None:
        return next((i.number for i in self.items.values() if i.kind == "pull_request" and i.head == branch), None)

    def create_pull(self, branch: str, base: str, title: str, body: str) -> int:
        self.calls.append(("create_pull", branch))
        number = next(self._numbers)
        self.items[number] = Item(number, "pull_request", BOT, title, body, head=branch)
        return number

    # fork pull requests -----------------------------------------------------------
    def open_fork_pull(self, author: Actor, fork: Path, branch: str, title: str) -> int:
        """Fetch the fork's branch into the base repository (as GitHub does under refs/pull/N/head)."""
        number = next(self._numbers)
        git(self.repo, "fetch", "-q", str(fork), f"{branch}:refs/pull/{number}/head")
        self.items[number] = Item(number, "pull_request", author, title, "", head=f"refs/pull/{number}/head")
        return number

    def pull_snapshot(self, number: int, base: str = "main") -> tuple[IntakeSnapshot, dict[str, bytes]]:
        item = self.items[number]
        head = git(self.repo, "rev-parse", f"refs/pull/{number}/head")
        base_sha = git(self.repo, "merge-base", base, head)
        changed, blobs = [], {}
        out = git(self.repo, "diff", "--no-renames", "--name-status", "-z", f"{base_sha}...{head}")
        parts = [p for p in out.split("\0") if p]
        for status, path in zip(parts[::2], parts[1::2]):
            entry = git(self.repo, "ls-tree", head, "--", path)
            mode, _, sha = entry.split("\t")[0].split(" ") if entry else ("000000", "", "0" * 40)
            content = subprocess.run(["git", "-C", str(self.repo), "cat-file", "blob", sha], capture_output=True).stdout if entry else b""
            changed.append(ChangedFile(path, {"A": "added", "D": "removed", "M": "modified"}.get(status, "modified"), sha, len(content), mode))
            blobs[path] = content
        snapshot = IntakeSnapshot(self.repository, "pull_request", number, item.state, item.author, item.title, item.body,
                                  "2026-10-12T00:00:00Z", tuple(item.labels), tuple(item.comments), head, base_sha,
                                  "contributor/research", tuple(changed))
        return snapshot, blobs
