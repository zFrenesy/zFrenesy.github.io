"""``normalize_intake``: an issue form plus authenticated answers become a candidate or questions (spec §5, §16.2).

The record is built with the same scaffolds as ``rp new`` and checked with the same
code as ``rp check`` before anything is written. Required before publication:
claim type and scope, model names (version may be ``unknown``), human roles,
contribution mode and the rights declarations. Anything missing becomes one of at
most three numbered questions with a suggested default. Legal declarations come
only from the author's own form checkboxes, never from answers or extraction.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from rp import strict_yaml
from rp.catalog import default_catalog
from rp.contribute.check import CheckReport, FolderFiles, check_folder
from rp.contribute.workspace import ContributorError, Research
from rp.fingerprint import ManifestError, manifest_from_blobs, scientific_fingerprint
from rp.identity.ids import IdSource, new_id
from rp.identity.paths import contribution_dir, problem_dir
from rp.intake import forms
from rp.intake.attachments import AttachmentReport, fetch_attachments
from rp.intake.snapshot import IntakeSnapshot
from rp.validation.problems import similar_statements

__all__ = ["Candidate", "Extractor", "NoExtractor", "Outcome", "Proposal", "Question", "ground", "normalize_intake"]

MAX_QUESTIONS = 3
DECLARATION_KEYS = frozenset({"rights", "public_disclosure", "ai_disclosure", "declarations", "authorship_confirmation"})
TITLE_PREFIX = re.compile(r"^(attempt|review|problem)\s*:\s*", re.IGNORECASE)
CLAIM_WORDS = ", ".join(c.replace("_", " ") for c in forms.CLAIM_TYPES)


@dataclass(frozen=True)
class Question:
    key: str
    text: str
    default: str | None = None


@dataclass(frozen=True)
class Proposal:
    """A value proposed by model extraction (Tier 2, milestone 4). Kept only if its quote is grounded."""
    key: str
    value: str
    quote: str


class Extractor(Protocol):
    def propose(self, snapshot: IntakeSnapshot, missing: list[str]) -> list[Proposal]: ...


class NoExtractor:
    """Milestone 3: no model extraction. Values come from form fields and the author's answers only."""

    def propose(self, snapshot: IntakeSnapshot, missing: list[str]) -> list[Proposal]:
        return []


def ground(proposals: Iterable[Proposal], texts: Iterable[str]) -> list[Proposal]:
    """Keep proposals whose verbatim quote occurs in contributor-written text; never legal declarations."""
    corpus = [t for t in texts if t]
    return [p for p in proposals
            if p.key not in DECLARATION_KEYS and len(p.quote.strip()) >= 3 and any(p.quote in t for t in corpus)]


@dataclass
class Candidate:
    kind: str
    folder: str
    files: FolderFiles
    record: dict[str, Any]
    fingerprint: str
    report: CheckReport

    @property
    def ok(self) -> bool:
        return self.report.ok


@dataclass
class Outcome:
    candidate: Candidate | None = None
    questions: list[Question] = field(default_factory=list)
    recorded: list[str] = field(default_factory=list)
    blocking: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    ids: dict[str, str] = field(default_factory=dict)


class _Builder:
    def __init__(self, snapshot: IntakeSnapshot, intake: forms.FormIntake, answers: dict[str, dict[str, Any]],
                 research: Research, ids: dict[str, str], id_source: IdSource | None):
        self.snapshot, self.intake, self.answers, self.research = snapshot, intake, answers, research
        self.ids, self.id_source = dict(ids), id_source
        self.questions: list[Question] = []
        self.recorded: list[str] = []
        self.blocking: list[str] = []

    # values -----------------------------------------------------------------
    def value(self, key: str) -> str | None:
        if key in self.answers:
            answer = self.answers[key]
            self.recorded.append(f"{key.replace('_', ' ').capitalize()}: recorded as “{answer['value'][:200]}” (from your reply: “{answer['quote'][:200]}”)")
            return answer["value"].strip() or None
        return self.intake.get(key)

    def ask(self, key: str, text: str, default: str | None = None) -> None:
        if all(q.key != key for q in self.questions):
            self.questions.append(Question(key, text, default))

    def stable(self, kind: str, key: str) -> str:
        if key not in self.ids:
            self.ids[key] = new_id(kind, self.id_source)
        return self.ids[key]

    # people and models ------------------------------------------------------
    def submitter(self, roles: list[str]) -> dict[str, Any]:
        author = self.snapshot.author
        return {"person_ref": self.stable("person", "submitter"), "github_id": author.id, "login_at_event": author.login,
                "display_name": author.login, "roles": roles, "authorship_confirmation": "confirmed"}

    def humans(self, mode: str | None, confirmations: dict[str, int]) -> list[dict[str, Any]] | None:
        people, unclear = forms.parse_people(self.value("people"))
        author = self.snapshot.author
        if unclear:
            self.ask("people", "What did each person do? One line each, for example “Ada (@ada): proved Lemma 2, wrote the draft”.",
                     f"@{author.login}: " + ("prompting, submission" if mode == "ai_only" else "investigation, writing"))
            return None
        if not people:
            if mode == "ai_only":
                return []
            self.ask("people", "Who contributed, and what did each person do? One line each.", f"@{author.login}: investigation, writing")
            return None
        result = []
        for index, person in enumerate(people):
            is_author = person.login is not None and person.login.lower() == author.login.lower()
            result.append({
                "person_ref": self.stable("person", "submitter") if is_author else self.stable("person", f"person:{index}"),
                "github_id": author.id if is_author else None,
                "login_at_event": person.login,
                "display_name": person.name,
                "roles": list(person.roles),
                "authorship_confirmation": "confirmed" if is_author else "listed_by_submitter",
            })
        return result

    def model_uses(self, mode: str | None) -> list[dict[str, Any]] | None:
        models, unparsed, none = forms.parse_models(self.value("models"))
        if unparsed:
            self.ask("models", "Which AI models were used? One per line: provider, model name, exact version or “unknown”, role.",
                     None)
            return None
        if not models and not none:
            self.ask("models", "Which AI models were used? One per line: provider, model name, version or “unknown”, role. Reply “none” if no AI was used.",
                     None if mode in ("ai_only", "human_ai") else "none")
            return None
        if none and mode in ("ai_only", "human_ai"):
            self.ask("models", "The form says AI was involved but lists no model. Which models were used (version may be “unknown”)?")
            return None
        return [{"provider": m.provider[:100], "declared_name": m.name[:200], "family": None, "version": m.version[:200], "role": m.role,
                 "settings": None, "generation_date": None, "provenance": {"level": "declared", "evidence": []}} for m in models]

    def declarations(self, actor: str) -> dict[str, Any]:
        confirmed = self.intake.all_declarations_ticked
        if not confirmed:
            self.ask("declarations", "Please tick all the declaration boxes by editing the form (the pencil icon on your first post). "
                     "Only you can confirm them; replies cannot.")
        entry = {"confirmed": confirmed, "source": "form_field", "actor": actor, "recorded_at": self.snapshot.created_at,
                 "evidence_url": self.snapshot.url}
        return {"rights": dict(entry), "public_disclosure": dict(entry), "ai_disclosure": dict(entry)}

    def title(self, fallback: str) -> str:
        text = TITLE_PREFIX.sub("", self.value("title") or self.snapshot.title).strip()
        text = re.sub(r"^[A-Z][A-Z0-9]{1,9}-[A-Z0-9][A-Z0-9.-]{0,80}\b\s*[-:—]?\s*", "", text).strip()
        return (text or fallback)[:300]


def _text_file(title: str, body: str) -> bytes:
    return (f"# {title}\n\n{body.strip()}\n").encode("utf-8")


def _attachments(builder: _Builder, report: AttachmentReport, files: FolderFiles, artifacts: list[dict]) -> None:
    for item in report.files:
        name = "files/attachments/" + item.name
        if name in files:
            continue
        files[name] = (item.content, "100644")
        suffix = name.rsplit(".", 1)[-1].lower()
        role = {"pdf": "manuscript", "tex": "manuscript_source", "bib": "bibliography", "png": "figure", "jpg": "figure",
                "jpeg": "figure", "csv": "data", "json": "data"}.get(suffix, "supplementary")
        media = {"pdf": "application/pdf", "tex": "application/x-tex", "bib": "application/x-bibtex", "png": "image/png", "jpg": "image/jpeg",
                 "jpeg": "image/jpeg", "csv": "text/csv", "json": "application/json", "md": "text/markdown"}.get(suffix, "text/plain")
        artifacts.append({"role": role, "location": "in_repository", "path": name, "media_type": media})
    builder.blocking.extend(report.errors)


def _problem(builder: _Builder, key: str) -> dict[str, Any] | None:
    alias = (builder.value(key) or "").strip().upper()
    if not alias:
        builder.ask(key, "Which problem is this for? Give its handle from the problem page, for example ERDOS-1.")
        return None
    try:
        return builder.research.problem(alias)
    except ContributorError:
        builder.ask(key, f"There is no problem with the handle “{alias[:40]}”. Which problem is this for? Copy the handle from the problem page.")
        return None


def _attempt(builder: _Builder, confirmations: dict[str, int], fetch) -> tuple[str, FolderFiles, dict] | None:
    problem = _problem(builder, "problem")
    claim = forms.claim_type(builder.value("claim"))
    if builder.value("claim") and claim is None:
        builder.ask("claim", f"Which claim fits best? One of: {CLAIM_WORDS}.", "exploration")
    elif claim is None:
        builder.ask("claim", f"What do you claim? One of: {CLAIM_WORDS}.", "exploration")
    scope = builder.value("scope")
    if not scope:
        builder.ask("scope", "What exactly is proved, disproved or found, under which assumptions, and what remains open?")
    mode = forms.contribution_mode(builder.value("mode"))
    if mode is None:
        builder.ask("mode", "Who did the work: “people with AI assistance”, “AI only” or “people only”?", "People with AI assistance")
    writeup = builder.value("writeup")
    attachments = fetch_attachments("\n".join(filter(None, [writeup, builder.snapshot.body])), fetch)
    if not writeup and not attachments.files:
        builder.ask("writeup", "Please paste your write-up in a reply, or attach a PDF or a zip of your .tex files.")
    models = builder.model_uses(mode)
    humans = builder.humans(mode, confirmations)
    if problem is None or None in (claim, scope, mode, models, humans) or (not writeup and not attachments.files):
        builder.declarations(builder.stable("person", "submitter"))
        return None
    roles = ["submission"] + (["prompting"] if mode == "ai_only" else [])
    submitter = builder.submitter(roles)
    record = builder.research.attempt_record(problem, {"login": builder.snapshot.author.login, "id": builder.snapshot.author.id})
    title = builder.title(f"{claim.replace('_', ' ').capitalize()} on {problem['alias']}")
    record.update({
        "contribution_id": builder.stable("contribution", "contribution_id"),
        "revision_id": builder.stable("revision", "revision_id"),
        "title": title,
        "claim": {"type": claim, "scope_statement": scope[:5000], "assumptions": [], "limitations": []},
        "attribution": {"submitter": submitter, "humans": humans, "organisations": [], "contribution_mode": mode},
        "model_uses": models,
        "rights": {"licence": "CC-BY-4.0", "redistribution": "permitted", "holders": [h["display_name"] for h in humans] or [submitter["display_name"]]},
        "declarations": builder.declarations(submitter["person_ref"]),
    })
    files: FolderFiles = {}
    artifacts: list[dict] = []
    if writeup:
        files["files/attempt.md"] = (_text_file(title, writeup), "100644")
        artifacts.append({"role": "manuscript", "location": "in_repository", "path": "files/attempt.md", "media_type": "text/markdown"})
    _attachments(builder, attachments, files, artifacts)
    record["artifacts"] = artifacts
    folder = contribution_dir(problem["id"], record["contribution_id"], "attempt").as_posix()
    return folder, files, record


def _review(builder: _Builder, confirmations: dict[str, int], fetch) -> tuple[str, FolderFiles, dict] | None:
    alias = (builder.value("contribution") or "").strip().upper()
    target = None
    if not alias:
        builder.ask("contribution", "Which contribution do you review? Give its handle, for example ERDOS-1-A3.")
    else:
        try:
            target = builder.research.contribution(alias)
        except ContributorError:
            builder.ask("contribution", f"There is no contribution “{alias[:40]}”. Which one do you review? Copy its handle from its page.")
    finding = forms.review_finding(builder.value("finding"))
    if finding is None:
        builder.ask("finding", "What did you find: supports, error found, gap found, counterexample, known result, reproduced, not reproduced, reference suggestion or comment?", "comment")
    checked, evidence = builder.value("checked_scope"), builder.value("evidence")
    if not checked:
        builder.ask("checked_scope", "What exactly did you check, and how?")
    if not evidence:
        builder.ask("evidence", "What is your evidence? Point to exact sections, lemmas or lines.")
    models = builder.model_uses(None)
    if target is None or None in (finding, checked, evidence, models):
        builder.declarations(builder.stable("person", "submitter"))
        return None
    home = builder.research.problem(target["home"])
    record = builder.research.review_record(target, home, {"login": builder.snapshot.author.login, "id": builder.snapshot.author.id})
    target_record = strict_yaml.load((target["folder"] / "contribution.yaml").read_bytes())
    listed = {p.get("github_id") for p in [target_record["attribution"]["submitter"], *target_record["attribution"]["humans"]]}
    kind = "author_response" if builder.snapshot.author.id in listed else "review"
    mode = "human_ai" if models else "human_only"
    submitter = builder.submitter(["submission", "validation"])
    record["targets"][0].pop("location", None)
    record.update({
        "contribution_id": builder.stable("contribution", "contribution_id"),
        "revision_id": builder.stable("revision", "revision_id"),
        "type": kind,
        "title": ("Response to review of " if kind == "author_response" else "Review of ") + target["alias"],
        "attribution": {"submitter": submitter, "humans": [dict(submitter, roles=["validation"])], "organisations": [], "contribution_mode": mode},
        "model_uses": models,
        "rights": {"licence": "CC-BY-4.0", "redistribution": "permitted", "holders": [submitter["display_name"]]},
        "declarations": builder.declarations(submitter["person_ref"]),
        "review": {"finding": finding, "checked_scope": checked[:5000], "evidence": evidence[:5000],
                   "conflicts_of_interest": (builder.value("conflicts") or "None declared.")[:500]},
    })
    files = {"files/review.md": (_text_file(record["title"], f"**Checked:** {checked}\n\n**Evidence:** {evidence}"), "100644")}
    folder = contribution_dir(home["id"], record["contribution_id"], kind).as_posix()
    return folder, files, record


def _citation(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    patterns = [("doi", r"\b(10\.[0-9]{4,9}/[^\s,;]+)"), ("arxiv", r"arxiv[.:/ ]+(?:abs/)?([0-9]{4}\.[0-9]{4,5}(?:v[1-9][0-9]*)?)"),
                ("isbn", r"\bISBN[: ]*([0-9X-]{10,17})"), ("url", r"(https://[^\s,;)]+)")]
    for kind, pattern in patterns:
        found = re.search(pattern, text, flags=re.IGNORECASE)
        if found:
            value = found.group(1).rstrip(".")
            if kind == "isbn":
                value = value.replace("-", "")
            return {"reference": {"kind": kind, "value": value}, "quote": text[:5000]}
    return None


def _problem_proposal(builder: _Builder, confirmations: dict[str, int], fetch) -> tuple[str, FolderFiles, dict] | None:
    kind = forms.problem_kind(builder.value("kind"))
    if kind is None:
        builder.ask("kind", "Is this a subproblem of an existing problem, an open problem from the literature, or a new question?", "New question")
    parent = None
    if kind == "derived" or builder.value("parent"):
        parent = _problem(builder, "parent")
    statement, motivation, checks = builder.value("statement"), builder.value("motivation"), builder.value("checks")
    if not statement:
        builder.ask("statement", "Please state the problem precisely, with every definition, assumption and range.")
    if not motivation:
        builder.ask("motivation", "Why is this question interesting, and how does it relate to known problems?")
    if not checks:
        builder.ask("checks", "Which cases did you check, and which literature and existing problems did you search for duplicates?")
    citation = _citation(builder.value("sources")) if kind == "literature" else None
    if kind == "literature" and citation is None:
        builder.ask("sources", "Where is this problem stated? Give a DOI, arXiv number, ISBN or stable link, with a page or section.")
    models = builder.model_uses(None)
    novelty = bool(builder.intake.declarations) and all(builder.intake.declarations.values())
    if None in (kind, statement, motivation, checks, models) or (kind == "derived" and parent is None) or (kind == "literature" and citation is None):
        builder.declarations(builder.stable("person", "submitter"))
        return None
    record = builder.research.problem_record(parent if kind == "derived" else None, {"login": builder.snapshot.author.login, "id": builder.snapshot.author.id})
    submitter = builder.submitter(["submission", "conceptualization"])
    title = builder.title(f"Question related to {parent['alias']}" if parent else "Proposed question")
    record.update({
        "problem_id": builder.stable("problem", "problem_id"),
        "statement_revision_id": builder.stable("statement_revision", "statement_revision_id"),
        "title": title,
        "kind": kind,
        "attribution": {"submitter": submitter, "humans": [dict(submitter, roles=["conceptualization"])], "organisations": [],
                        "contribution_mode": "human_ai" if models else "human_only"},
        "model_uses": models,
        "rights": {"licence": "CC-BY-4.0", "redistribution": "permitted", "holders": [submitter["display_name"]]},
    })
    if parent is not None and kind != "derived":
        record["relations"] = [{"type": "related", "target_problem_id": parent["id"], "primary": False}]
    if kind != "derived":
        record.pop("derivation", None)
        if not _discipline_and_code(builder, record):
            return None
    if kind == "proposed":
        record["proposal"] = {"motivation": motivation[:5000], "relation_to_known": motivation[:5000], "elementary_checks": checks[:5000],
                              "literature_search": checks[:5000], "novelty_disclaimer_acknowledged": True}
        if not novelty:
            builder.ask("declarations", "Please tick all the declaration boxes by editing the form, including the one about novelty.")
        if "duplicates" in builder.answers:
            difference = builder.answers["duplicates"]["value"]
            record["proposal"]["relation_to_known"] = (motivation + "\n\nDifference from similar problems: " + difference)[:5000]
    else:
        record.pop("proposal", None)
    if kind == "literature":
        record["citation"] = citation
    if "duplicates" not in builder.answers and kind != "derived":
        similar = similar_statements(statement, record["disciplines"][0]["discipline"], builder.research.root, exclude=record["problem_id"])
        if similar:
            names = "; ".join(f"{s.title[:60]} ({s.path})" for s in similar)
            builder.ask("duplicates", f"This looks similar to: {names}. How does your question differ? Or reply “variant” if it is a variant.")
    files = {"statement.md": (_text_file(title, statement), "100644")}
    return problem_dir(record["problem_id"]).as_posix(), files, record


def _discipline_and_code(builder: _Builder, record: dict[str, Any]) -> bool:
    """Set the discipline and classification of a non-derived problem from the form or answers."""
    catalog = default_catalog()
    names = {catalog.disciplines[s]["name"].lower(): s for s in catalog.open_disciplines()}
    names.update({s: s for s in catalog.open_disciplines()})
    chosen = (builder.value("discipline") or "").strip().lower()
    slug = names.get(chosen)
    if slug is None:
        options = ", ".join(catalog.disciplines[s]["name"] for s in catalog.open_disciplines())
        builder.ask("discipline", f"Which discipline is this question in? One of: {options}.")
        return False
    record["disciplines"] = [{"discipline": slug, "role": "primary"}]
    scheme = catalog.disciplines[slug]["classification"]
    if not scheme:
        record["classifications"] = []
        return True
    code = (builder.value("classification") or "").strip()
    problem = catalog.classification_problem(scheme["scheme"], code) if code else "missing"
    if problem:
        builder.ask("classification", f"Which {scheme['name']} code fits best?" + (f" “{code[:30]}” is not one." if code else ""))
        return False
    record["classifications"] = [{"scheme": scheme["scheme"], "code": code}]
    return True


BUILDERS: dict[str, Callable] = {"attempt": _attempt, "review": _review, "problem": _problem_proposal}


def normalize_intake(snapshot: IntakeSnapshot, answers: dict[str, dict[str, Any]], research: Research, *,
                     ids: dict[str, str] | None = None, confirmations: dict[str, int] | None = None,
                     id_source: IdSource | None = None, fetch=None, extractor: Extractor | None = None) -> Outcome:
    kind = forms.detect_kind(snapshot.body, snapshot.labels)
    if kind is None:
        return Outcome(blocking=["this issue was not created from one of the submission forms"], ids=dict(ids or {}))
    intake = forms.parse_form(snapshot.body, kind)
    texts = [snapshot.body] + [c.body for c in snapshot.comments if c.author.id == snapshot.author.id]
    extracted = {}
    for proposal in ground((extractor or NoExtractor()).propose(snapshot, []), texts):
        if not intake.get(proposal.key) and proposal.key not in answers:
            extracted[proposal.key] = {"value": proposal.value, "quote": proposal.quote, "comment_id": 0}
    builder = _Builder(snapshot, intake, {**extracted, **answers}, research, ids or {}, id_source)
    built = BUILDERS[kind](builder, confirmations or {}, fetch)
    outcome = Outcome(questions=builder.questions[:MAX_QUESTIONS], recorded=builder.recorded, blocking=builder.blocking, ids=builder.ids)
    if built is None or builder.questions:
        return outcome
    folder, files, record = built
    yaml_name = "problem.yaml" if kind == "problem" else "contribution.yaml"
    files = {yaml_name: (strict_yaml.dump(record).encode("utf-8"), "100644"), **files}
    report = check_folder(research.root, folder, files)
    if kind == "problem":
        fingerprint = ""
    else:
        try:
            manifest = manifest_from_blobs({n: v for n, v in files.items() if n.startswith("files/")}, record["artifacts"])
            fingerprint = scientific_fingerprint(record, manifest)
        except ManifestError as exc:
            report.errors.append(str(exc))
            fingerprint = ""
    outcome.candidate = Candidate(record.get("type", "problem"), folder, files, record, fingerprint, report)
    return outcome

