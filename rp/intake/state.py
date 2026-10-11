"""Durable intake state, kept in one App-authored comment on the issue or PR (spec §6, §9).

The state is trusted only from a comment that GitHub attributes to the intake App
(``performed_via_github_app.id``). Anyone can paste the marker into their own
comment; such copies are ignored and reported. Status values follow §6.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from rp.intake.snapshot import Comment, IntakeSnapshot

__all__ = ["IntakeState", "MARKER", "STATUSES", "load_state", "render_state"]

MARKER = "<!-- rp-intake-state v1 "
_STATE = re.compile(r"<!-- rp-intake-state v1 (\{.*?\}) -->", re.DOTALL)
STATUSES = ("draft", "needs-information", "queued", "screening", "revision-requested", "eligible", "on-hold",
            "withdrawn", "stale", "publication-pending", "published")
MAX_STATE_BYTES = 60_000


@dataclass
class IntakeState:
    status: str = "draft"
    ids: dict[str, str] = field(default_factory=dict)
    questions: list[dict[str, Any]] = field(default_factory=list)
    asked_at: str | None = None
    answers: dict[str, dict[str, Any]] = field(default_factory=dict)
    last_comment_id: int = 0
    reminders: list[int] = field(default_factory=list)
    rounds: int = 0
    proposed_label: str | None = None
    confirmations: dict[str, int] = field(default_factory=dict)  # GitHub ID -> confirming comment ID
    publication_pr: int | None = None
    candidate_fingerprint: str | None = None
    appeal: str | None = None
    status_before_close: str | None = None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def load_state(snapshot: IntakeSnapshot, app_id: int) -> tuple[IntakeState, Comment | None, list[Comment]]:
    """(state, the App comment holding it, forged copies). The newest App-authored state wins."""
    trusted, forged = None, []
    for comment in snapshot.comments:
        found = _STATE.search(comment.body)
        if not found:
            continue
        if comment.app_id != app_id:
            forged.append(comment)
            continue
        trusted = (comment, found.group(1))
    if trusted is None:
        return IntakeState(), None, forged
    comment, text = trusted
    data = json.loads(text)
    known = {k: v for k, v in data.items() if k in IntakeState.__dataclass_fields__}
    return IntakeState(**known), comment, forged


def render_state(state: IntakeState, summary: str) -> str:
    payload = json.dumps(state.to_json(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    if len(payload) > MAX_STATE_BYTES:
        raise ValueError("intake state is too large for a comment")
    # "-->" cannot occur in JSON produced with ensure_ascii from these fields, but guard anyway.
    payload = payload.replace("-->", "--\\u003e")
    return f"{summary.rstrip()}\n\n{MARKER}{payload} -->\n"
