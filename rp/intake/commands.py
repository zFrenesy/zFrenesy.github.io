"""Comment commands (spec §16.3).

A command is the exact first line of a comment. Only the intake App acts on them;
who may use each command is checked against GitHub's numeric account IDs, never
logins or text. Commands are rate-limited per user and ignored on closed items
(except ``/reopen``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from rp.intake.snapshot import Comment
from rp.vocab import CLAIM_TYPES

__all__ = ["Command", "RATE_LIMIT", "parse_command", "permitted", "rate_limited"]

RATE_LIMIT = 10  # commands per user per hour
MAX_ROUNDS = 5
_PATTERNS = {
    "review": re.compile(r"/review"),
    "recheck": re.compile(r"/recheck"),
    "accept-label": re.compile(r"/accept-label (" + "|".join(CLAIM_TYPES) + r")"),
    "confirm-authorship": re.compile(r"/confirm-authorship"),
    "withdraw": re.compile(r"/withdraw"),
    "reopen": re.compile(r"/reopen"),
    "appeal": re.compile(r"/appeal (\S.{0,500})"),
}
WHO = {
    "review": {"author", "maintainer"},
    "recheck": {"author", "maintainer"},
    "accept-label": {"author"},
    "confirm-authorship": {"coauthor"},
    "withdraw": {"author", "maintainer"},
    "reopen": {"author", "maintainer"},
    "appeal": {"author"},
}


@dataclass(frozen=True)
class Command:
    name: str
    argument: str | None
    comment: Comment


def parse_command(comment: Comment) -> Command | None:
    first = comment.body.replace("\r\n", "\n").split("\n", 1)[0].rstrip()
    for name, pattern in _PATTERNS.items():
        found = pattern.fullmatch(first)
        if found:
            return Command(name, found.group(1) if found.groups() else None, comment)
    return None


def permitted(command: Command, *, author_id: int, maintainers: frozenset[int], coauthor_ids: frozenset[int]) -> bool:
    actor = command.comment.author.id
    roles = set()
    if actor == author_id:
        roles.add("author")
    if actor in maintainers:
        roles.add("maintainer")
    if actor in coauthor_ids:
        roles.add("coauthor")
    return bool(roles & WHO[command.name])


def _instant(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def rate_limited(command: Command, earlier: list[Command]) -> bool:
    """True when the same user already issued RATE_LIMIT commands in the hour before this one."""
    now = _instant(command.comment.created_at)
    window = [c for c in earlier if c.comment.author.id == command.comment.author.id
              and now - timedelta(hours=1) < _instant(c.comment.created_at) <= now and c.comment.id != command.comment.id]
    return len(window) >= RATE_LIMIT
