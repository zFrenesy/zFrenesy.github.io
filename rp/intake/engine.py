"""The intake bot's decision function: snapshot in, a plan of GitHub actions out (spec §6, §16).

``process`` is pure: it reads an immutable snapshot and the research tree and
returns the new state plus the exact actions to take. ``rp.intake.publication``
executes a plan through a ``GitHubPort``; every action is idempotent, so replaying
the same snapshot after a crash repeats nothing.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from rp import strict_yaml
from rp.contribute.check import FolderFiles, folder_key, check_folder
from rp.contribute.workspace import Research
from rp.identity.ids import IdSource
from rp.intake.answers import parse_answers
from rp.intake.commands import MAX_ROUNDS, parse_command, permitted, rate_limited
from rp.intake.normalize import Candidate, Extractor, Outcome, normalize_intake
from rp.intake.snapshot import IntakeSnapshot
from rp.intake.state import IntakeState, load_state
from rp.validation.records import publication_issues

__all__ = ["Action", "Plan", "process", "REMINDER_DAYS", "STALE_DAYS"]

REMINDER_DAYS = (7, 21)
STALE_DAYS = 30
CLOSED_STATUSES = {"withdrawn", "stale"}
HELD_STATUSES = {"withdrawn", "stale", "on-hold"}


@dataclass(frozen=True)
class Action:
    kind: str  # comment, labels, close, reopen, publish, incorporate
    params: dict[str, Any]


@dataclass
class Plan:
    state: IntakeState
    actions: list[Action] = field(default_factory=list)
    outcome: Outcome | None = None
    warnings: list[str] = field(default_factory=list)

    def comment(self, key: str, body: str) -> None:
        self.actions.append(Action("comment", {"key": key, "body": body}))


def _days(since: str, now: str) -> int:
    parse = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
    return (parse(now) - parse(since)).days


def files_digest(files: FolderFiles) -> str:
    digest = hashlib.sha256()
    for name in sorted(files):
        content, mode = files[name]
        digest.update(name.encode() + b"\0" + mode.encode() + b"\0" + hashlib.sha256(content).digest())
    return "sha256:" + digest.hexdigest()


def _questions_text(outcome: Outcome) -> str:
    lines = ["Thanks for your submission. A few details are needed before it can be queued:", ""]
    for number, question in enumerate(outcome.questions, 1):
        default = f" (suggested: {question.default})" if question.default else ""
        lines.append(f"{number}. {question.text}{default}")
    lines += ["", "Reply in plain words, numbering your answers (for example “1. partial result”). “yes” accepts a suggestion."]
    if outcome.recorded:
        lines += ["", "Recorded so far:", *[f"- {r}" for r in outcome.recorded]]
    return "\n".join(lines)


def _apply_commands(snapshot: IntakeSnapshot, state: IntakeState, plan: Plan, app_id: int) -> None:
    new = sorted((c for c in snapshot.comments if c.id > state.last_comment_id and c.app_id != app_id), key=lambda c: c.id)
    earlier = [cmd for c in snapshot.comments if c.id <= state.last_comment_id and (cmd := parse_command(c))]
    coauthors = frozenset(int(k) for k in state.ids.get("coauthor_ids", "").split(",") if k)
    for comment in new:
        command = parse_command(comment)
        if command is None:
            if comment.author.id == snapshot.author.id and state.questions and state.status not in HELD_STATUSES:
                state.answers.update(parse_answers(comment, state.questions))
            continue
        if snapshot.state == "closed" and command.name != "reopen":
            continue
        if rate_limited(command, earlier):
            plan.warnings.append(f"comment {comment.id}: command rate limit reached for {comment.author.login}")
            continue
        earlier.append(command)
        logins = {login.lower() for login in state.ids.get("coauthor_logins", "").split(",") if login}
        is_coauthor = comment.author.id in coauthors or comment.author.login.lower() in logins
        if not permitted(command, author_id=snapshot.author.id, maintainers=snapshot.maintainers,
                         coauthor_ids=frozenset({comment.author.id}) if is_coauthor else frozenset()):
            plan.warnings.append(f"comment {comment.id}: {comment.author.login} may not use /{command.name} here")
            continue
        name = command.name
        if name == "withdraw":
            state.status_before_close = state.status
            state.status = "withdrawn"
            plan.actions.append(Action("close", {"reason": "not_planned"}))
            plan.comment(f"withdrawn:{comment.id}", "Withdrawn at the author's request. `/reopen` restores it.")
        elif name == "reopen" and state.status in CLOSED_STATUSES:
            state.status, state.asked_at, state.reminders = "needs-information", None, []
            plan.actions.append(Action("reopen", {}))
        elif name == "appeal":
            state.status, state.appeal = "on-hold", command.argument
            plan.comment(f"appeal:{comment.id}", "This submission is on hold for a maintainer. The appeal is the only human step and is optional.")
        elif name in ("review", "recheck"):
            if name == "recheck":
                state.rounds += 1
            if state.rounds > MAX_ROUNDS:
                plan.comment(f"rounds:{state.rounds}", "The screening round limit is reached. If only non-blocking notes remain you may "
                             "publish with unresolved screening notes; otherwise use `/appeal <reason>`.")
        elif name == "accept-label":
            if state.proposed_label == command.argument:
                state.answers["claim"] = {"value": command.argument, "quote": comment.body.split("\n", 1)[0], "comment_id": comment.id}
                state.proposed_label = None
            else:
                plan.comment(f"label:{comment.id}", "No corrected claim label is waiting for confirmation.")
        elif name == "confirm-authorship":
            state.confirmations[str(comment.author.id)] = comment.id
    if new:
        state.last_comment_id = max(state.last_comment_id, *(c.id for c in new))


def _confirm_coauthors(candidate: Candidate, snapshot: IntakeSnapshot, state: IntakeState) -> None:
    """Apply /confirm-authorship from listed co-authors (matched by their login at the event)."""
    humans = candidate.record.get("attribution", {}).get("humans", [])
    by_login = {c.author.login.lower(): c.author for c in snapshot.comments if str(c.author.id) in state.confirmations}
    for person in humans:
        login = (person.get("login_at_event") or "").lower()
        if person["authorship_confirmation"] == "listed_by_submitter" and login in by_login:
            person["authorship_confirmation"] = "confirmed"
            person["github_id"] = by_login[login].id


def _process_issue(snapshot: IntakeSnapshot, research: Research, state: IntakeState, plan: Plan, now: str, **options: Any) -> None:
    outcome = normalize_intake(snapshot, state.answers, research, ids=state.ids, confirmations=state.confirmations, **options)
    plan.outcome = outcome
    state.ids.update(outcome.ids)
    if outcome.candidate is not None:
        humans = outcome.candidate.record.get("attribution", {}).get("humans", [])
        state.ids["coauthor_logins"] = ",".join(sorted(h["login_at_event"] for h in humans if h.get("login_at_event") and h["github_id"] != snapshot.author.id))
    if outcome.questions or outcome.blocking or (outcome.candidate is not None and not outcome.candidate.ok):
        questions = [{"number": n, "key": q.key, "text": q.text, "default": q.default} for n, q in enumerate(outcome.questions, 1)]
        problems = list(outcome.blocking) + (outcome.candidate.report.errors if outcome.candidate else [])
        if questions != state.questions or state.status != "needs-information":
            state.questions, state.asked_at, state.reminders = questions, now, []
            body = _questions_text(outcome) if questions else "Thanks for your submission."
            if problems:
                body += "\n\nPlease fix these by editing your form:\n" + "\n".join(f"- {p}" for p in problems[:10])
            plan.comment("ask:" + hashlib.sha256(body.encode()).hexdigest()[:16], body)
        state.status = "needs-information"
        _reminders(state, plan, now)
        return
    candidate = outcome.candidate
    if candidate is None:
        return
    _confirm_coauthors(candidate, snapshot, state)
    yaml_name = "problem.yaml" if candidate.kind == "problem" else "contribution.yaml"
    candidate.files[yaml_name] = (strict_yaml.dump(candidate.record).encode("utf-8"), "100644")
    digest = files_digest(candidate.files)
    state.questions, state.asked_at, state.reminders = [], None, []
    state.status = "queued"
    if digest != state.candidate_fingerprint or state.publication_pr is None:
        state.candidate_fingerprint = digest
        plan.actions.append(Action("publish", {"branch": f"intake/issue-{snapshot.number}", "folder": candidate.folder,
                                               "files": candidate.files, "digest": digest, "title": candidate.record["title"]}))
        recorded = "\n".join(f"- {r}" for r in outcome.recorded)
        plan.comment(f"queued:{digest[7:23]}", "Thanks. Everything needed is recorded" + (":\n" + recorded if recorded else ".")
                     + "\n\nA publication pull request holds your contribution. It waits in the queue for screening and publication; "
                       "nothing is merged by hand.")


def _reminders(state: IntakeState, plan: Plan, now: str) -> None:
    if state.status != "needs-information" or not state.asked_at:
        return
    days = _days(state.asked_at, now)
    if days >= STALE_DAYS:
        state.status_before_close, state.status = state.status, "stale"
        plan.actions.append(Action("close", {"reason": "not_planned"}))
        plan.comment(f"stale:{state.asked_at}", "Closed after 30 days without the missing details. Reply `/reopen` to continue.")
        return
    for mark in REMINDER_DAYS:
        if days >= mark and mark not in state.reminders:
            state.reminders.append(mark)
            plan.comment(f"remind:{mark}:{state.asked_at}", f"A reminder: this submission is waiting for the details asked above ({days} days ago).")


def _process_pull(snapshot: IntakeSnapshot, research: Research, state: IntakeState, plan: Plan, now: str, blobs: dict[str, bytes]) -> None:
    files = snapshot.files or ()
    changes = []
    for item in files:
        status = {"added": "A", "removed": "D", "renamed": "R", "copied": "C"}.get(item.status, "M")
        changes.append((status, item.path))
        if item.previous_path:
            changes.append(("D", item.previous_path))
    errors, folders = [], []
    for status, path in changes:
        if status != "A":
            errors.append(f"{path}: only new files may be added (status {status})")
    if not errors:
        grouped: dict[str, FolderFiles] = {}
        for item in files:
            key = folder_key(item.path)
            if key is None:
                errors.append(f"{item.path}: outside a new contribution, review or problem folder")
                continue
            folder = key[1]
            grouped.setdefault(folder, {})[item.path[len(folder) + 1:]] = (blobs.get(item.path, b""), item.mode)
        if len(grouped) != 1:
            errors.append("a pull request must add exactly one new folder")
        for folder, folder_files in grouped.items():
            report = check_folder(research.root, folder, folder_files)
            errors.extend(report.errors)
            folders.append((folder, folder_files, report))
    if not errors:
        folder, folder_files, _ = folders[0]
        name = "problem.yaml" if "/contributions/" not in folder and "/reviews/" not in folder else "contribution.yaml"
        record = strict_yaml.load(folder_files[name][0])
        if name == "contribution.yaml":
            errors.extend(f"{i.message}: confirm it by running `rp submit` yourself at a terminal, or edit `declarations` in your own commit"
                          for i in publication_issues(record) if i.code == "publication.declaration_unconfirmed")
    if errors:
        state.status = "needs-information"
        body = "Thanks for the pull request. It cannot be queued yet:\n" + "\n".join(f"- {e}" for e in errors[:15])
        plan.comment("pr-errors:" + hashlib.sha256(body.encode()).hexdigest()[:16], body)
        return
    digest = files_digest(folder_files)
    state.status = "queued"
    if digest != state.candidate_fingerprint or state.publication_pr is None:
        state.candidate_fingerprint = digest
        plan.actions.append(Action("incorporate", {"branch": f"intake/pr-{snapshot.number}", "head_sha": snapshot.head_sha,
                                                   "source_pr": snapshot.number, "folder": folder, "digest": digest,
                                                   "author": {"login": snapshot.author.login, "id": snapshot.author.id},
                                                   "title": record["title"]}))


def process(snapshot: IntakeSnapshot, research: Research, *, app_id: int, now: str, id_source: IdSource | None = None,
            fetch=None, extractor: Extractor | None = None, blobs: dict[str, bytes] | None = None) -> Plan:
    state, _, forged = load_state(snapshot, app_id)
    plan = Plan(state)
    plan.warnings.extend(f"comment {c.id} by {c.author.login} imitates the intake state and was ignored" for c in forged)
    _apply_commands(snapshot, state, plan, app_id)
    if state.status in HELD_STATUSES:
        plan.actions.append(Action("labels", {"status": state.status}))
        return plan
    if snapshot.kind == "pull_request":
        _process_pull(snapshot, research, state, plan, now, blobs or {})
    else:
        _process_issue(snapshot, research, state, plan, now, id_source=id_source, fetch=fetch, extractor=extractor)
    plan.actions.append(Action("labels", {"status": state.status}))
    return plan
