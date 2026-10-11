"""Storage paths in the research authoring tree (§3).

``problems/<shard>/<problem-id>/`` where the shard is the first two hex digits
of the problem UUID. Contributions live under ``contributions/<id>/`` and
reviews (review-like types) under ``reviews/<id>/`` of their home problem.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from rp.identity.ids import InvalidIdentifier, is_id, parse_id
from rp.vocab import REVIEW_LIKE_TYPES

__all__ = [
    "InvalidPath",
    "ResearchPath",
    "check_relative_path",
    "contribution_dir",
    "parse_research_path",
    "problem_dir",
    "problem_shard",
]

PROBLEMS_ROOT = PurePosixPath("problems")
_SEGMENT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]*")


class InvalidPath(ValueError):
    pass


def problem_shard(problem_id: str) -> str:
    return parse_id(problem_id, "problem").hex[:2]


def problem_dir(problem_id: str) -> PurePosixPath:
    return PROBLEMS_ROOT / problem_shard(problem_id) / problem_id


def contribution_dir(problem_id: str, contribution_id: str, contribution_type: str) -> PurePosixPath:
    parse_id(contribution_id, "contribution")
    area = "reviews" if contribution_type in REVIEW_LIKE_TYPES else "contributions"
    return problem_dir(problem_id) / area / contribution_id


def check_relative_path(path: str) -> PurePosixPath:
    """Validate a repository-relative POSIX path from untrusted input.

    Rejects absolute paths, backslashes, empty, ``.`` and ``..`` segments,
    hidden segments, control characters and anything outside a conservative
    character set.
    """
    if not isinstance(path, str) or not path:
        raise InvalidPath("path must be a non-empty string")
    if path.startswith("/") or "\\" in path or "\x00" in path:
        raise InvalidPath(f"{path!r} must be relative and use forward slashes")
    parts = path.split("/")
    for part in parts:
        if part in ("", ".", ".."):
            raise InvalidPath(f"{path!r} contains an empty, '.' or '..' segment")
        if not _SEGMENT.fullmatch(part):
            raise InvalidPath(f"{path!r} has a disallowed segment {part!r}")
    return PurePosixPath(*parts)


@dataclass(frozen=True, slots=True)
class ResearchPath:
    problem_id: str
    area: str  # "problem" | "contributions" | "reviews"
    entity_id: str | None
    rest: str  # path below the problem or contribution folder


def parse_research_path(path: str) -> ResearchPath:
    """Classify a path under ``problems/``; raise InvalidPath if it is outside the grammar."""
    clean = check_relative_path(path)
    parts = clean.parts
    if len(parts) < 4 or parts[0] != "problems":
        raise InvalidPath(f"{path!r} is not under problems/<shard>/<problem-id>/")
    shard, problem_id = parts[1], parts[2]
    try:
        if problem_shard(problem_id) != shard:
            raise InvalidPath(f"{path!r} is in shard {shard!r} but {problem_id} belongs in {problem_shard(problem_id)!r}")
    except InvalidIdentifier as exc:
        raise InvalidPath(f"{path!r}: {exc}") from exc
    if parts[3] in ("contributions", "reviews"):
        if len(parts) < 6 or not is_id(parts[4], "contribution"):
            raise InvalidPath(f"{path!r} must name a file inside {parts[3]}/<contribution-id>/")
        return ResearchPath(problem_id, parts[3], parts[4], "/".join(parts[5:]))
    return ResearchPath(problem_id, "problem", None, "/".join(parts[3:]))
