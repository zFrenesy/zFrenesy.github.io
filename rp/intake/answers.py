"""Plain-word replies to the numbered intake questions (spec §16.2).

Only the issue author answers questions. A reply may number its answers
(``1. yes``, ``2: GPT-5, unknown``) or, when one question is open, simply answer
it. "yes", "ok" or "default" accepts the suggested default. Commands are never
answers, and answers can never confirm a legal declaration.
"""

from __future__ import annotations

import re
from typing import Any

from rp.intake.snapshot import Comment

__all__ = ["parse_answers"]

ACCEPT = {"yes", "y", "ok", "okay", "default", "accept", "agreed", "fine", "correct"}
_NUMBERED = re.compile(r"^\s*(\d{1,2})\s*[.):\-]\s*(.*)$")
NOT_ANSWERABLE = frozenset({"declarations"})


def _resolve(question: dict[str, Any], text: str) -> str | None:
    text = text.strip()
    if not text:
        return None
    if text.lower().rstrip(".!") in ACCEPT:
        return question.get("default")
    return text


def parse_answers(comment: Comment, questions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Answers in one comment, keyed by question key: {value, quote, comment_id}."""
    if not questions or comment.body.lstrip().startswith("/"):
        return {}
    by_number = {q["number"]: q for q in questions}
    lines = comment.body.replace("\r\n", "\n").split("\n")
    found: dict[int, list[str]] = {}
    current = None
    for line in lines:
        match = _NUMBERED.match(line)
        if match and int(match.group(1)) in by_number:
            current = int(match.group(1))
            found[current] = [match.group(2)]
        elif current is not None:
            found[current].append(line)
    if not found and len(questions) == 1:
        found = {questions[0]["number"]: lines}
    answers = {}
    for number, chunk in found.items():
        question = by_number[number]
        if question["key"] in NOT_ANSWERABLE:
            continue
        text = "\n".join(chunk).strip()
        value = _resolve(question, text)
        if value is not None:
            answers[question["key"]] = {"value": value, "quote": text[:2000], "comment_id": comment.id}
    return answers
