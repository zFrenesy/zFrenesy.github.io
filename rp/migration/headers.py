"""Legacy TeX header comments, parsed as data only.

Headers are ``% KEY: value`` comment lines (JSON for some keys). Malformed,
duplicated or conflicting headers are recorded as issues; nothing is guessed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from rp.timeutil import is_calendar_date

__all__ = ["HEADER_KEYS", "JSON_KEYS", "Headers", "parse_headers"]

HEADER_KEYS = (
    "FIRST_POSTED",
    "ATTEMPT_STATUS",
    "ENTRY_KIND",
    "MODEL",
    "TOP_PROBLEM",
    "ECONOMICS_PROBLEM",
    "OPENAI_CLAIM",
    "COLLECTION_METADATA",
    "RECOVERY_PROVENANCE",
    "REVISION_OF",
    "REVISION_VERSION",
    "REVISION_BASIS",
    "COMPLETION",
    "RESEARCH_GENERATED",
    "ATTEMPT_ORIGIN",
    "GAME_THEORY_PROBLEM",
)
JSON_KEYS = frozenset({"TOP_PROBLEM", "ECONOMICS_PROBLEM", "OPENAI_CLAIM", "COLLECTION_METADATA", "RECOVERY_PROVENANCE", "GAME_THEORY_PROBLEM"})
ATTEMPT_STATUSES = ("solved", "partial", "unresolved")
_PATTERNS = {key: re.compile(rf"^[ \t]*%[ \t]*{key}:[ \t]*([^\r\n]*)", re.M) for key in HEADER_KEYS}


@dataclass
class Headers:
    values: dict[str, list[str]] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)

    def first(self, key: str) -> str | None:
        found = self.values.get(key)
        return found[0] if found else None

    @property
    def first_posted(self) -> str | None:
        value = self.first("FIRST_POSTED")
        return value if value and is_calendar_date(value) else None

    @property
    def attempt_status(self) -> str | None:
        statuses = {v.strip().lower() for v in self.values.get("ATTEMPT_STATUS", [])}
        return next(iter(statuses)) if len(statuses) == 1 and statuses <= set(ATTEMPT_STATUSES) else None

    @property
    def entry_kind(self) -> str | None:
        return self.first("ENTRY_KIND")

    def summary(self) -> dict[str, Any]:
        return {key: (self.data[key] if key in self.data else (vals[0] if len(vals) == 1 else vals)) for key, vals in sorted(self.values.items())}


def parse_headers(text: str) -> Headers:
    headers = Headers()
    for key, pattern in _PATTERNS.items():
        found = [v.strip() for v in pattern.findall(text)]
        if not found:
            continue
        headers.values[key] = found
        if len(set(found)) > 1:
            headers.issues.append(f"{key} appears {len(found)} times with different values")
        if key in JSON_KEYS:
            try:
                headers.data[key] = json.loads(found[0])
            except json.JSONDecodeError:
                headers.issues.append(f"{key} is not valid JSON")
    posted = headers.first("FIRST_POSTED")
    if posted is not None and posted != "null" and not is_calendar_date(posted):
        headers.issues.append(f"FIRST_POSTED {posted!r} is not a calendar date")
    statuses = {v.strip().lower() for v in headers.values.get("ATTEMPT_STATUS", [])}
    if statuses - set(ATTEMPT_STATUSES):
        headers.issues.append(f"unknown ATTEMPT_STATUS {sorted(statuses - set(ATTEMPT_STATUSES))}")
    if len(statuses) > 1:
        headers.issues.append("conflicting ATTEMPT_STATUS declarations")
    return headers
