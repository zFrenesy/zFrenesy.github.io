"""Parse GitHub's rendered issue-form bodies (spec §6, §16.2).

GitHub renders each form field as ``### <label>`` followed by the answer,
``_No response_`` for an empty optional field, and ``- [X] <label>`` for ticked
checkboxes. Labels come from the issue-form templates in the research kit, so the
parser and the forms cannot drift apart. Free-text answers (models, people) are
parsed conservatively: anything unclear is reported, never guessed.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from rp.vocab import CLAIM_TYPES, CONTRIBUTION_MODES, REVIEW_FINDINGS

__all__ = ["FormIntake", "FORM_KINDS", "ModelLine", "PersonLine", "parse_form", "parse_models", "parse_people"]

TEMPLATES = Path(__file__).resolve().parents[1] / "contribute" / "kit" / "templates"
FORM_KINDS = {"attempt": "issue-attempt.yml", "review": "issue-review.yml", "problem": "issue-problem.yml"}
NO_RESPONSE = "_No response_"

MODE_CHOICES = {
    "People with LLM assistance": "human_ai",
    "LLM only (people only prompted or submitted)": "ai_only",
    "People with AI assistance": "human_ai",
    "AI only (people only prompted or submitted)": "ai_only",
    "People only": "human_only",
}
FINDING_CHOICES = {"Supports the claim": "supports"}
PROBLEM_KIND_CHOICES = {
    "Subproblem, special case or step of the parent": "derived",
    "Open problem from the literature": "literature",
    "New question": "proposed",
}
ROLE_WORDS = [
    (r"\bprompt", "prompting"),
    (r"\bsubmit", "submission"),
    (r"\bidea|\bconcept|\bposed|\bproposed", "conceptualization"),
    (r"\bcod(e|ing)\b|\bsoftware|\bprogram", "software"),
    (r"\bmethod", "methodology"),
    (r"\bformal analysis", "formal_analysis"),
    (r"\bsupervis", "supervision"),
    (r"\bdata\b", "data_curation"),
    (r"\bcheck|\bverif|\bvalidat", "validation"),
    (r"\bedit|\brevis", "writing_review_editing"),
    (r"\bwr(ote|ite|iting)|\bdraft", "writing_original_draft"),
    (r"\bprov|\bproof|\bresearch|\binvestigat|\bmath|\bargument|\bsolv", "investigation"),
]
MODEL_ROLE_WORDS = [
    (r"\bproof search|\bsearch", "proof_search"),
    (r"\bcomput|\bcalculat|\bnumeric", "computation"),
    (r"\breview|\bcheck", "review_assistance"),
    (r"\btranslat", "translation"),
    (r"\bedit|\bformat|\bpolish", "editing"),
    (r"\bdraft|\bgenerat|\bwr(ote|ite)|\bproof|\bargument|\bsolution", "generated_draft"),
]
_LOGIN = re.compile(r"@([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))")
_SEPARATOR = re.compile(r"\s*(?::|—|–|\s-\s)\s*")


@functools.cache
def _labels(kind: str) -> dict[str, tuple[str, str]]:
    """label -> (field id, field type) for one form."""
    form = yaml.safe_load((TEMPLATES / FORM_KINDS[kind]).read_text(encoding="utf-8"))
    labels = {item["attributes"]["label"]: (item["id"], item["type"]) for item in form["body"] if item.get("id")}
    # Existing submitted forms remain readable after the interface terminology change.
    for label, field in list(labels.items()):
        if label == "LLMs used":
            labels["AI models used"] = field
    return labels


@functools.cache
def _checkbox_labels(kind: str) -> tuple[str, ...]:
    form = yaml.safe_load((TEMPLATES / FORM_KINDS[kind]).read_text(encoding="utf-8"))
    for item in form["body"]:
        if item.get("id") == "declarations":
            return tuple(option["label"] for option in item["attributes"]["options"])
    return ()


@dataclass
class FormIntake:
    kind: str
    fields: dict[str, str | None] = field(default_factory=dict)
    declarations: dict[str, bool] = field(default_factory=dict)  # checkbox label -> ticked
    unknown_sections: list[str] = field(default_factory=list)

    def get(self, key: str) -> str | None:
        value = self.fields.get(key)
        return value if value else None

    @property
    def all_declarations_ticked(self) -> bool:
        labels = _checkbox_labels(self.kind)
        return bool(labels) and all(self.declarations.get(label) for label in labels)


def detect_kind(body: str, labels: tuple[str, ...] = ()) -> str | None:
    headings = set(re.findall(r"^### (.+?)\s*$", body, flags=re.MULTILINE))
    for kind in FORM_KINDS:
        if kind in labels and headings & set(_labels(kind)):
            return kind
    scores = {kind: len(headings & set(_labels(kind))) for kind in FORM_KINDS}
    best = max(scores, key=scores.get)
    return best if scores[best] >= 3 else None


def parse_form(body: str, kind: str) -> FormIntake:
    labels = _labels(kind)
    result = FormIntake(kind)
    parts = re.split(r"^### (.+?)\s*$", body.replace("\r\n", "\n"), flags=re.MULTILINE)
    for heading, text in zip(parts[1::2], parts[2::2]):
        text = text.strip("\n")
        if heading not in labels:
            result.unknown_sections.append(heading)
            continue
        key, kind_of = labels[heading]
        if kind_of == "checkboxes":
            for line in text.splitlines():
                found = re.match(r"^- \[([ xX])\] (.+?)\s*$", line)
                if found:
                    label = found.group(2)
                    label = label.replace("Every AI model and person", "Every LLM and person")
                    result.declarations[label] = found.group(1) in "xX"
            continue
        value = text.strip()
        result.fields[key] = None if value in ("", NO_RESPONSE) else value
    return result


def choice(value: str | None, table: dict[str, str], vocabulary: tuple[str, ...]) -> str | None:
    """Map a dropdown label to its vocabulary value, or None if it is not one of the options."""
    if value is None:
        return None
    if value in table:
        return table[value]
    slug = value.strip().lower().replace(" ", "_")
    return slug if slug in vocabulary else None


def claim_type(value: str | None) -> str | None:
    return choice(value, {}, CLAIM_TYPES)


def contribution_mode(value: str | None) -> str | None:
    return choice(value, MODE_CHOICES, CONTRIBUTION_MODES)


def review_finding(value: str | None) -> str | None:
    return choice(value, FINDING_CHOICES, REVIEW_FINDINGS)


def problem_kind(value: str | None) -> str | None:
    return PROBLEM_KIND_CHOICES.get(value or "")


@dataclass(frozen=True)
class ModelLine:
    provider: str
    name: str
    version: str
    role: str
    quote: str


@dataclass(frozen=True)
class PersonLine:
    name: str
    login: str | None
    roles: tuple[str, ...]
    quote: str


def _roles(text: str, table: list[tuple[str, str]]) -> list[str]:
    found = []
    for pattern, role in table:
        if re.search(pattern, text, flags=re.IGNORECASE) and role not in found:
            found.append(role)
    return found


def parse_models(text: str | None) -> tuple[list[ModelLine], list[str], bool]:
    """(models, unparsed lines, explicitly none). Versions missing or unclear stay 'unknown'."""
    if text is None:
        return [], [], False
    lines = [line.strip(" -*\t") for line in text.splitlines() if line.strip(" -*\t")]
    if len(lines) == 1 and lines[0].strip().lower().rstrip(".") in ("none", "no", "n/a", "no ai", "none used"):
        return [], [], True
    models, unparsed = [], []
    for line in lines:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2 or not all(parts[:2]):
            unparsed.append(line)
            continue
        provider, name = parts[0], parts[1]
        version = parts[2] if len(parts) > 2 and parts[2] else "unknown"
        if version.lower() in ("unknown", "?", "n/a", "not known", "not sure"):
            version = "unknown"
        role_text = ", ".join(parts[3:])
        roles = _roles(role_text, MODEL_ROLE_WORDS)
        role = roles[0] if roles else "other"
        models.append(ModelLine(provider, name, version, role, line))
    return models, unparsed, False


def parse_people(text: str | None) -> tuple[list[PersonLine], list[str]]:
    """(people, lines whose roles could not be read). Format: ``Name (@login): what they did``."""
    if text is None:
        return [], []
    people, unclear = [], []
    for line in (raw.strip(" -*\t") for raw in text.splitlines()):
        if not line:
            continue
        login_match = _LOGIN.search(line)
        login = login_match.group(1) if login_match else None
        pieces = _SEPARATOR.split(line, maxsplit=1)
        head, rest = pieces[0], pieces[1] if len(pieces) > 1 else ""
        name = re.sub(r"\(?@[A-Za-z0-9-]+\)?", "", head).strip(" ,()") or login or head.strip()
        roles = _roles(rest, ROLE_WORDS)
        if not roles:
            unclear.append(line)
        people.append(PersonLine(name[:200], login, tuple(roles), line))
    return people, unclear
