"""Revision-targeted reviews and disputes (spec §17).

Reviews attach to one exact contribution revision and never transfer to another.
A specific objection (``error_found``, ``gap_found``, ``counterexample``) marks that
revision Disputed until one of the following happens:

- the objector retracts it (a later review with ``review.retracts`` naming it);
- the objector, or any reviewer of a *later* revision of the same contribution,
  responds to it (``review.responds_to``) with a finding that is not an objection;
- 90 days pass after an author response with no further review from the objector,
  which shows "Response given; objector has not replied".

Nothing is deleted and the platform never rules on who is right. Reviews are
counted by finding, never turned into votes or a score.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from rp.vocab import OBJECTION_FINDINGS

__all__ = ["Objection", "ReviewInput", "RevisionReviews", "summarise_reviews", "NO_REPLY_DAYS"]

NO_REPLY_DAYS = 90
STATE_TEXT = {
    "open": "Open objection",
    "retracted": "Withdrawn by the objector",
    "resolved": "Marked resolved",
    "response_no_reply": "Response given; objector has not replied",
}


@dataclass(frozen=True)
class ReviewInput:
    record: Mapping[str, Any]
    reviewer: str  # stable key: GitHub numeric ID when known, else the person reference
    on: date  # when the review was recorded (ledger acceptance)
    alias: str = ""

    @property
    def ref(self) -> tuple[str, str]:
        return self.record["contribution_id"], self.record["revision_id"]

    @property
    def target(self) -> tuple[str, str] | None:
        targets = [t for t in self.record["targets"] if t["target_kind"] == "contribution_revision"]
        return (targets[0]["contribution_id"], targets[0]["revision_id"]) if len(targets) == 1 else None

    @property
    def finding(self) -> str:
        return self.record.get("review", {}).get("finding", "comment")

    def points_to(self, key: str) -> tuple[str, str] | None:
        ref = self.record.get("review", {}).get(key)
        return (ref["contribution_id"], ref["revision_id"]) if ref else None


@dataclass
class Objection:
    review: ReviewInput
    state: str = "open"
    by: ReviewInput | None = None

    @property
    def text(self) -> str:
        return STATE_TEXT[self.state]


@dataclass
class RevisionReviews:
    contribution_id: str
    revision_id: str
    counts: Counter = field(default_factory=Counter)
    reviews: list[ReviewInput] = field(default_factory=list)
    responses: list[ReviewInput] = field(default_factory=list)
    objections: list[Objection] = field(default_factory=list)

    @property
    def disputed(self) -> bool:
        return any(o.state == "open" for o in self.objections)

    @property
    def note(self) -> str | None:
        if self.disputed:
            return "Disputed"
        if any(o.state == "response_no_reply" for o in self.objections):
            return STATE_TEXT["response_no_reply"]
        return None


def summarise_reviews(reviews: Iterable[ReviewInput], revision_order: Mapping[str, list[str]], today: date) -> dict[tuple[str, str], RevisionReviews]:
    """Per (contribution, revision): counts by finding, author responses and objection states.

    ``revision_order`` lists each contribution's accepted revision IDs, oldest first.
    """
    reviews = sorted(reviews, key=lambda r: (r.on, r.ref))
    summary: dict[tuple[str, str], RevisionReviews] = {}
    by_ref = {r.ref: r for r in reviews}

    def entry(target: tuple[str, str]) -> RevisionReviews:
        return summary.setdefault(target, RevisionReviews(*target))

    for review in reviews:
        target = review.target
        if target is None:
            continue
        item = entry(target)
        if review.record["type"] == "author_response":
            item.responses.append(review)
            continue
        item.reviews.append(review)
        item.counts[review.finding] += 1
        if review.finding in OBJECTION_FINDINGS:
            item.objections.append(Objection(review))

    later: dict[tuple[str, str], set[str]] = {}
    for cid, order in revision_order.items():
        for index, rid in enumerate(order):
            later[(cid, rid)] = set(order[index + 1:])
    replies = defaultdict(list)
    for review in reviews:
        for key in ("responds_to", "retracts"):
            if (ref := review.points_to(key)) in by_ref:
                replies[ref].append((key, review))

    for item in summary.values():
        for objection in item.objections:
            mine = objection.review
            for key, reply in replies[mine.ref]:
                if reply.on < mine.on:
                    continue
                if key == "retracts" and reply.reviewer == mine.reviewer:
                    objection.state, objection.by = "retracted", reply
                    break
                if key == "responds_to" and reply.record["type"] == "review" and reply.finding not in OBJECTION_FINDINGS:
                    target = reply.target
                    on_later = target is not None and target[0] == item.contribution_id and target[1] in later.get((item.contribution_id, item.revision_id), set())
                    if reply.reviewer == mine.reviewer or on_later:
                        objection.state, objection.by = "resolved", reply
                        break
            if objection.state != "open":
                continue
            answers = [r for k, r in replies[mine.ref] if k == "responds_to" and r.record["type"] == "author_response"]
            if answers:
                first = min(answers, key=lambda r: r.on)
                objector_since = any(r.reviewer == mine.reviewer and r.on > first.on for r in reviews)
                if not objector_since and today - first.on >= timedelta(days=NO_REPLY_DAYS):
                    objection.state, objection.by = "response_no_reply", first
    return summary
