"""Immutable snapshots of an issue or pull request, as read from GitHub (spec §5, §7).

Everything here is untrusted contributor data except the numeric account IDs and
the App ID of a comment, which GitHub authenticates. Listings must be complete:
a truncated or short page sequence raises ``IncompleteListing`` so callers fail
closed instead of checking a partial change set.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

__all__ = ["Actor", "ChangedFile", "Comment", "IncompleteListing", "IntakeSnapshot", "collect_pages", "PR_FILES_CAP"]

# GitHub's pull-request files API returns at most 3000 files.
PR_FILES_CAP = 3000


class IncompleteListing(RuntimeError):
    pass


@dataclass(frozen=True)
class Actor:
    login: str
    id: int


@dataclass(frozen=True)
class Comment:
    id: int
    author: Actor
    body: str
    created_at: str  # UTC instant from GitHub
    app_id: int | None = None  # performed_via_github_app.id; set only by GitHub for App-authored comments


@dataclass(frozen=True)
class ChangedFile:
    path: str
    status: str  # added, modified, removed, renamed, copied, changed, unchanged
    sha: str
    size: int
    mode: str  # git mode at the head ("100644", "100755", "120000", "160000")
    previous_path: str | None = None


@dataclass(frozen=True)
class IntakeSnapshot:
    repository: str
    kind: str  # "issue" or "pull_request"
    number: int
    state: str  # "open" or "closed"
    author: Actor
    title: str
    body: str
    created_at: str
    labels: tuple[str, ...] = ()
    comments: tuple[Comment, ...] = ()
    head_sha: str | None = None
    base_sha: str | None = None
    head_repository: str | None = None
    files: tuple[ChangedFile, ...] | None = None
    maintainers: frozenset[int] = field(default_factory=frozenset)

    @property
    def url(self) -> str:
        kind = "issues" if self.kind == "issue" else "pull"
        return f"https://github.com/{self.repository}/{kind}/{self.number}"


def collect_pages(pages: Iterable[Sequence], *, expected: int | None, per_page: int, cap: int | None = None) -> list:
    """Concatenate API pages and prove the listing is complete.

    ``expected`` is the total the API reports separately (e.g. a PR's ``changed_files``).
    A short page that is not the last, a total that differs from ``expected``, or a
    listing that reaches the API's cap all raise ``IncompleteListing``.
    """
    items: list = []
    finished = False
    for page in pages:
        if finished:
            raise IncompleteListing("a page arrived after a short page")
        items.extend(page)
        if len(page) < per_page:
            finished = True
    if expected is not None and len(items) != expected:
        raise IncompleteListing(f"listed {len(items)} items but the API reports {expected}")
    if cap is not None and len(items) >= cap:
        raise IncompleteListing(f"the listing reached the API limit of {cap} items")
    return items
