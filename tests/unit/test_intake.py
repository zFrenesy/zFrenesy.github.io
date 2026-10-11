"""Intake: issue forms, questions, commands, state and managed publication PRs, against a fake GitHub."""

import io
import os
import subprocess
import zipfile
from pathlib import Path

import pytest
import yaml

from rp import strict_yaml
from rp.contribute.check import check_folder
from rp.contribute.workspace import Research
from rp.identity.ids import SeededIdSource
from rp.intake import forms
from rp.intake.answers import parse_answers
from rp.intake.attachments import fetch_attachments
from rp.intake.engine import process
from rp.intake.normalize import Proposal, ground
from rp.intake.publication import apply_plan
from rp.intake.snapshot import Actor, Comment, IncompleteListing, collect_pages
from rp.intake.state import load_state
from rp.migration.importer import LegacyImporter
from rp.migration.legacy_git import LegacyRepo
from rp.timeutil import FixedClock
from tests.fixtures.fake_github import APP_ID, BOT, FakeGitHub, git
from tests.fixtures.legacy_repo import SNAPSHOT, build_legacy_repo

AUTHOR = Actor("contributor-x", 424242)
STRANGER = Actor("someone-else", 5555)
MAINTAINER = Actor("maintainer-m", 7)
LEGACY_AUTHOR = Actor("mehmetmars7", 243585043)
DAY0 = "2026-10-12T00:00:00Z"
TEMPLATES = Path(forms.TEMPLATES)
CONTRIBUTOR_ENV = {"GIT_AUTHOR_NAME": "Contributor X", "GIT_AUTHOR_EMAIL": "cx@example.org", "GIT_AUTHOR_DATE": "2026-10-10T08:00:00Z",
                   "GIT_COMMITTER_NAME": "Contributor X", "GIT_COMMITTER_EMAIL": "cx@example.org", "GIT_COMMITTER_DATE": "2026-10-10T08:00:00Z"}


def render_form(kind, values, ticks=True):
    form = yaml.safe_load((TEMPLATES / forms.FORM_KINDS[kind]).read_text())
    parts = []
    for item in form["body"]:
        if not item.get("id"):
            continue
        label = item["attributes"]["label"]
        if item["type"] == "checkboxes":
            boxes = "\n".join(f"- [{'X' if ticks else ' '}] {o['label']}" for o in item["attributes"]["options"])
            parts.append(f"### {label}\n\n{boxes}")
        else:
            parts.append(f"### {label}\n\n{values.get(item['id']) or '_No response_'}")
    return "\n\n".join(parts) + "\n"


ATTEMPT = {
    "problem": "TOP-10", "claim": "Partial result", "scope": "We prove the case n = 2 only.",
    "writeup": "## Argument\n\nFor $n = 2$ the claim follows from parity. See https://arxiv.org/abs/2101.00001.",
    "mode": "People with AI assistance", "models": "OpenAI, GPT-5, unknown, generated the draft",
    "people": "Contributor X (@contributor-x): proved the case and wrote the draft\nAda (@ada-l): checked the computations",
}


@pytest.fixture(scope="module")
def imported(tmp_path_factory):
    legacy_path, commit = build_legacy_repo(tmp_path_factory.mktemp("legacy"))
    work = tmp_path_factory.mktemp("work")
    LegacyImporter(LegacyRepo(legacy_path, commit), work, id_source=SeededIdSource("intake"),
                   clock=FixedClock("2026-10-11T00:00:00Z"), snapshot=SNAPSHOT).run()
    return work / "research"


@pytest.fixture
def research(imported, tmp_path):
    root = tmp_path / "research"
    subprocess.run(["cp", "-R", str(imported), str(root)], check=True)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "Import")
    return Research(root)


def run(gh, number, research, now=DAY0, **extra):
    snapshot = gh.snapshot(number, maintainers=frozenset({MAINTAINER.id}), **extra)
    plan = process(snapshot, research, app_id=APP_ID, now=now, id_source=SeededIdSource(f"run-{number}"))
    apply_plan(plan, gh, snapshot, app_id=APP_ID)
    return plan


def state_of(gh, number):
    return load_state(gh.snapshot(number), APP_ID)[0]


# --------------------------------------------------------------------------- forms


def test_form_parsing_and_detection():
    body = render_form("attempt", {**ATTEMPT, "references": None})
    assert forms.detect_kind(body) == "attempt"
    intake = forms.parse_form(body, "attempt")
    assert intake.get("problem") == "TOP-10" and intake.get("references") is None and intake.all_declarations_ticked
    assert forms.claim_type(intake.get("claim")) == "partial_result"
    assert forms.contribution_mode(intake.get("mode")) == "human_ai"
    assert not forms.parse_form(render_form("attempt", ATTEMPT, ticks=False), "attempt").all_declarations_ticked
    assert forms.detect_kind("Hello, I solved it!") is None
    models, unparsed, none = forms.parse_models("OpenAI, GPT-5\n???")
    assert models[0].version == "unknown" and unparsed == ["???"] and not none


def test_grounding_discards_unquoted_values_and_declarations():
    texts = ["We prove the case n = 2 using GPT-5."]
    kept = ground([Proposal("models", "OpenAI, GPT-5", "using GPT-5"), Proposal("models", "x", "not in text"),
                   Proposal("rights", "yes", "We prove")], texts)
    assert [p.value for p in kept] == ["OpenAI, GPT-5"]


def test_listing_completeness():
    assert collect_pages([[1, 2], [3]], expected=3, per_page=2) == [1, 2, 3]
    with pytest.raises(IncompleteListing):
        collect_pages([[1, 2], [3]], expected=4, per_page=2)
    with pytest.raises(IncompleteListing):
        collect_pages([[1], [2]], expected=2, per_page=2)
    with pytest.raises(IncompleteListing):
        collect_pages([[1, 2]], expected=2, per_page=2, cap=2)


# --------------------------------------------------------------------------- form intake


def test_complete_form_becomes_a_publication_pr(research):
    gh = FakeGitHub(research.root)
    number = gh.open_issue(AUTHOR, "Attempt: TOP-10 The case n = 2", render_form("attempt", ATTEMPT), labels=["intake", "attempt"])
    plan = run(gh, number, research)
    assert plan.state.status == "queued" and plan.outcome.candidate.ok, plan.outcome.candidate.report.render()
    record = plan.outcome.candidate.record
    assert record["title"] == "The case n = 2" and record["claim"]["type"] == "partial_result"
    assert record["declarations"]["rights"] == {"confirmed": True, "source": "form_field", "actor": record["attribution"]["submitter"]["person_ref"],
                                                "recorded_at": DAY0, "evidence_url": f"https://github.com/we-solve-staging/research/issues/{number}"}
    humans = {h["login_at_event"]: h for h in record["attribution"]["humans"]}
    assert humans["contributor-x"]["authorship_confirmation"] == "confirmed" and humans["contributor-x"]["github_id"] == AUTHOR.id
    assert humans["ada-l"]["authorship_confirmation"] == "listed_by_submitter" and humans["ada-l"]["github_id"] is None
    pr = gh.find_pull(f"intake/issue-{number}")
    assert pr is not None and plan.state.publication_pr == pr
    sha = gh.branch_sha(f"intake/issue-{number}")
    assert git(research.root, "log", "-1", "--format=%an", sha) == "we-solve-intake[bot]"
    files = git(research.root, "diff", "--name-only", "main", sha).splitlines()
    assert {f.rsplit("/", 1)[-1] for f in files} == {"contribution.yaml", "attempt.md"}
    assert "intake: queued" in gh.items[number].labels
    state = state_of(gh, number)
    assert state.status == "queued" and state.publication_pr == pr


def test_replaying_the_same_snapshot_changes_nothing(research):
    gh = FakeGitHub(research.root)
    number = gh.open_issue(AUTHOR, "Attempt: TOP-10", render_form("attempt", ATTEMPT), labels=["intake", "attempt"])
    run(gh, number, research)
    before = list(gh.calls)
    plan = run(gh, number, research)
    assert gh.calls == before, gh.calls[len(before):]
    assert not [a for a in plan.actions if a.kind == "publish"]


def test_missing_details_become_at_most_three_questions(research):
    gh = FakeGitHub(research.root)
    values = {**ATTEMPT, "claim": None, "scope": None, "models": None, "people": None}
    number = gh.open_issue(AUTHOR, "Attempt: TOP-10", render_form("attempt", values), labels=["intake", "attempt"])
    plan = run(gh, number, research)
    assert plan.state.status == "needs-information" and len(plan.state.questions) == 3
    assert [q["key"] for q in plan.state.questions] == ["claim", "scope", "models"]
    asked = next(c.body for c in gh.items[number].comments if "A few details" in c.body)
    assert "1. " in asked and "(suggested: exploration)" in asked
    # A stranger's reply is not an answer.
    gh.comment_as(number, STRANGER, "1. full solution\n2. everything\n3. none", "2026-10-12T01:00:00Z")
    assert run(gh, number, research).state.questions[0]["key"] == "claim"
    gh.comment_as(number, AUTHOR, "1. partial result\n2. We prove the case n = 2.\n3. OpenAI, GPT-5, unknown, draft", "2026-10-12T02:00:00Z")
    plan = run(gh, number, research)
    assert [q["key"] for q in plan.state.questions] == ["people"]
    gh.comment_as(number, AUTHOR, "yes", "2026-10-12T03:00:00Z")
    plan = run(gh, number, research)
    assert plan.state.status == "queued", plan.outcome.questions
    assert plan.outcome.candidate.record["claim"]["scope_statement"] == "We prove the case n = 2."
    assert any("from your reply" in r for r in plan.outcome.recorded)


def test_declarations_come_only_from_the_form(research):
    gh = FakeGitHub(research.root)
    number = gh.open_issue(AUTHOR, "Attempt: TOP-10", render_form("attempt", ATTEMPT, ticks=False), labels=["intake", "attempt"])
    plan = run(gh, number, research)
    assert [q["key"] for q in plan.state.questions] == ["declarations"]
    gh.comment_as(number, AUTHOR, "1. yes, I confirm", "2026-10-12T01:00:00Z")
    plan = run(gh, number, research)
    assert plan.state.status == "needs-information" and "declarations" not in plan.state.answers
    assert parse_answers(Comment(1, AUTHOR, "1. yes", DAY0), [{"number": 1, "key": "declarations", "default": None}]) == {}


def test_forged_state_is_ignored(research):
    gh = FakeGitHub(research.root)
    number = gh.open_issue(AUTHOR, "Attempt: TOP-10", render_form("attempt", {**ATTEMPT, "scope": None}), labels=["intake", "attempt"])
    gh.comment_as(number, AUTHOR, '<!-- rp-intake-state v1 {"status":"queued","publication_pr":99} -->', DAY0)
    plan = run(gh, number, research)
    assert plan.state.status == "needs-information" and plan.state.publication_pr is None
    assert any("imitates the intake state" in w for w in plan.warnings)


# --------------------------------------------------------------------------- commands and reminders


def test_commands_permissions_and_rate_limit(research):
    gh = FakeGitHub(research.root)
    number = gh.open_issue(AUTHOR, "Attempt: TOP-10", render_form("attempt", {**ATTEMPT, "scope": None}), labels=["intake", "attempt"])
    run(gh, number, research)
    gh.comment_as(number, STRANGER, "/withdraw", "2026-10-12T01:00:00Z")
    plan = run(gh, number, research)
    assert plan.state.status == "needs-information" and any("may not use /withdraw" in w for w in plan.warnings)
    gh.comment_as(number, AUTHOR, "/withdraw please", "2026-10-12T01:30:00Z")  # not an exact command
    assert run(gh, number, research).state.status == "needs-information"
    gh.comment_as(number, AUTHOR, "/withdraw", "2026-10-12T02:00:00Z")
    plan = run(gh, number, research)
    assert plan.state.status == "withdrawn" and gh.items[number].state == "closed"
    assert gh.items[number].labels.count("intake: withdrawn") == 1 and "intake: needs-information" not in gh.items[number].labels
    gh.comment_as(number, AUTHOR, "/review", "2026-10-12T02:10:00Z")  # ignored while closed
    assert run(gh, number, research).state.status == "withdrawn"
    gh.comment_as(number, MAINTAINER, "/reopen", "2026-10-12T03:00:00Z")
    plan = run(gh, number, research)
    assert plan.state.status == "needs-information" and gh.items[number].state == "open"
    for minute in range(11):
        gh.comment_as(number, AUTHOR, "/recheck", f"2026-10-12T04:{minute:02d}:00Z")
    plan = run(gh, number, research)
    assert plan.state.rounds == 10 and any("rate limit" in w for w in plan.warnings)


def test_appeal_puts_the_item_on_hold(research):
    gh = FakeGitHub(research.root)
    number = gh.open_issue(AUTHOR, "Attempt: TOP-10", render_form("attempt", {**ATTEMPT, "scope": None}), labels=["intake", "attempt"])
    gh.comment_as(number, AUTHOR, "/appeal the question about scope does not apply", "2026-10-12T01:00:00Z")
    plan = run(gh, number, research)
    assert plan.state.status == "on-hold" and plan.state.appeal.startswith("the question")


def test_reminders_then_stale_then_reopen(research):
    gh = FakeGitHub(research.root)
    number = gh.open_issue(AUTHOR, "Attempt: TOP-10", render_form("attempt", {**ATTEMPT, "scope": None}), labels=["intake", "attempt"])
    run(gh, number, research)
    run(gh, number, research, now="2026-10-19T00:00:00Z")
    run(gh, number, research, now="2026-10-19T12:00:00Z")
    run(gh, number, research, now="2026-11-02T00:00:00Z")
    reminders = [c for c in gh.items[number].comments if "A reminder" in c.body]
    assert len(reminders) == 2
    plan = run(gh, number, research, now="2026-11-11T00:00:00Z")
    assert plan.state.status == "stale" and gh.items[number].state == "closed"
    gh.comment_as(number, AUTHOR, "/reopen", "2026-11-12T00:00:00Z")
    plan = run(gh, number, research, now="2026-11-12T00:00:00Z")
    assert plan.state.status == "needs-information" and gh.items[number].state == "open"


def test_listed_coauthor_confirms_authorship(research):
    gh = FakeGitHub(research.root)
    number = gh.open_issue(AUTHOR, "Attempt: TOP-10", render_form("attempt", ATTEMPT), labels=["intake", "attempt"])
    run(gh, number, research)
    gh.comment_as(number, Actor("ada-l", 31337), "/confirm-authorship", "2026-10-12T05:00:00Z")
    gh.comment_as(number, STRANGER, "/confirm-authorship", "2026-10-12T05:01:00Z")
    plan = run(gh, number, research)
    humans = {h["login_at_event"]: h for h in plan.outcome.candidate.record["attribution"]["humans"]}
    assert humans["ada-l"]["authorship_confirmation"] == "confirmed" and humans["ada-l"]["github_id"] == 31337
    assert str(STRANGER.id) not in plan.state.confirmations
    record = strict_yaml.load(git(research.root, "show", f"intake/issue-{number}:{plan.outcome.candidate.folder}/contribution.yaml").encode())
    assert {h["login_at_event"]: h["authorship_confirmation"] for h in record["attribution"]["humans"]}["ada-l"] == "confirmed"


# --------------------------------------------------------------------------- reviews and problems


def test_review_by_a_listed_author_is_an_author_response(research):
    gh = FakeGitHub(research.root)
    values = {"contribution": "ERDOS-1-A1", "finding": "Comment", "checked_scope": "Section 2", "evidence": "The bound in Lemma 3 is sharp.", "models": "none"}
    review = gh.open_issue(STRANGER, "Review: ERDOS-1-A1", render_form("review", values), labels=["intake", "review"])
    response = gh.open_issue(LEGACY_AUTHOR, "Review: ERDOS-1-A1", render_form("review", values), labels=["intake", "review"])
    first, second = run(gh, review, research), run(gh, response, research)
    assert first.outcome.candidate.ok and first.outcome.candidate.record["type"] == "review"
    assert second.outcome.candidate.ok, second.outcome.candidate.report.render()
    assert second.outcome.candidate.record["type"] == "author_response" and "/reviews/" in second.outcome.candidate.folder


def test_subproblem_form(research):
    gh = FakeGitHub(research.root)
    values = {"parent": "TOP-10", "kind": "Subproblem, special case or step of the parent",
              "statement": "Let $n = 2$. Decide whether the statement of the parent problem holds for every admissible parameter.",
              "motivation": "The smallest open case.", "checks": "Checked n = 1 by hand; searched the catalogue.", "models": "none"}
    number = gh.open_issue(AUTHOR, "Problem: the case n = 2", render_form("problem", values), labels=["intake", "problem"])
    plan = run(gh, number, research)
    candidate = plan.outcome.candidate
    assert candidate is not None and candidate.ok, (plan.outcome.questions, candidate and candidate.report.render())
    assert candidate.record["kind"] == "derived" and candidate.record["derivation"]["parent_status_unchanged"] is True


# --------------------------------------------------------------------------- fork pull requests


def contributor_fork(research, tmp_path, *, confirm=True, tamper=False):
    fork = tmp_path / "fork"
    subprocess.run(["git", "clone", "-q", str(research.root), str(fork)], check=True)
    folder = Research(fork).new_attempt("TOP-10", {"login": AUTHOR.login, "id": AUTHOR.id, "name": "Contributor X"})
    record = strict_yaml.load((folder / "contribution.yaml").read_bytes())
    record["model_uses"][0].update(provider="openai", declared_name="GPT-5")
    record["title"], record["claim"]["scope_statement"] = "The case n = 2", "We prove the case n = 2."
    for key in record["declarations"]:
        record["declarations"][key]["confirmed"] = confirm
    (folder / "contribution.yaml").write_text(strict_yaml.dump(record))
    (folder / "files" / "attempt.md").write_text("# The case n = 2\n\nBy parity.\n")
    if tamper:
        problem = next(fork.glob("problems/*/*/problem.yaml"))
        problem.write_text(problem.read_text() + "# edited\n")
    env = {**os.environ, **CONTRIBUTOR_ENV}
    subprocess.run(["git", "-C", str(fork), "switch", "-q", "-c", "contrib"], check=True, env=env)
    subprocess.run(["git", "-C", str(fork), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(fork), "commit", "-q", "-m", "Add attempt"], check=True, env=env)
    return fork


def test_fork_pr_is_incorporated_with_authorship_unchanged(research, tmp_path):
    gh = FakeGitHub(research.root)
    fork = contributor_fork(research, tmp_path)
    number = gh.open_fork_pull(AUTHOR, fork, "contrib", "Add attempt")
    original = git(research.root, "log", "--format=%H %an <%ae> %aI %cn <%ce> %cI", f"refs/pull/{number}/head", "-1")
    snapshot, blobs = gh.pull_snapshot(number)
    plan = process(snapshot, research, app_id=APP_ID, now=DAY0, blobs=blobs)
    assert plan.state.status == "queued", [a.params.get("body") for a in plan.actions if a.kind == "comment"]
    apply_plan(plan, gh, snapshot, app_id=APP_ID)
    publication = gh.find_pull(f"intake/pr-{number}")
    assert publication is not None and publication != number
    carried = git(research.root, "log", "--format=%H %an <%ae> %aI %cn <%ce> %cI", f"intake/pr-{number}", "-1")
    assert carried == original and "Contributor X <cx@example.org> 2026-10-10T08:00:00" in carried
    source = gh.items[number]
    assert source.state == "closed" and any(f"Incorporated into #{publication}" in c.body for c in source.comments)
    assert "carries your commits unchanged" in next(c.body for c in source.comments if "Incorporated" in c.body)
    assert f"#{number}" in gh.items[publication].body and f"GitHub ID {AUTHOR.id}" in gh.items[publication].body


@pytest.mark.parametrize("confirm, tamper, message", [(False, False, "declaration is not confirmed"), (True, True, "only new files may be added")])
def test_fork_pr_problems_are_reported_not_incorporated(research, tmp_path, confirm, tamper, message):
    gh = FakeGitHub(research.root)
    fork = contributor_fork(research, tmp_path, confirm=confirm, tamper=tamper)
    number = gh.open_fork_pull(AUTHOR, fork, "contrib", "Add attempt")
    snapshot, blobs = gh.pull_snapshot(number)
    plan = process(snapshot, research, app_id=APP_ID, now=DAY0, blobs=blobs)
    apply_plan(plan, gh, snapshot, app_id=APP_ID)
    assert plan.state.status == "needs-information" and gh.find_pull(f"intake/pr-{number}") is None
    assert any(message in c.body for c in gh.items[number].comments)


# --------------------------------------------------------------------------- attachments


def zip_bytes(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data, *mode in entries:
            info = zipfile.ZipInfo(name)
            if mode:
                info.external_attr = mode[0] << 16
            archive.writestr(info, data)
    return buffer.getvalue()


@pytest.mark.parametrize("entries, message", [
    ([("../evil.tex", b"x")], "segment"),
    ([("/abs.tex", b"x")], ""),
    ([("link.tex", b"target", 0o120777)], "symbolic link"),
    ([("a.tex", b"x"), ("A.tex", b"y")], "appears twice"),
    ([("inner.zip", b"x")], "nested"),
    ([("run.sh", b"echo")], "not accepted"),
    ([("big.txt", b"0" * (6 * 1024 * 1024))], "larger than 5 MiB"),
])
def test_hostile_archives_are_rejected(entries, message):
    url = "https://github.com/user-attachments/files/1/paper.zip"
    report = fetch_attachments(f"See {url}", lambda u: ("paper.zip", zip_bytes(entries)))
    assert report.errors and message in " ".join(report.errors)


def test_good_attachments_are_kept():
    url = "https://github.com/user-attachments/files/2/proof.zip"
    pdf = "https://github.com/user-attachments/files/3/notes.pdf"
    fetched = {url: ("proof.zip", zip_bytes([("main.tex", b"\\section{x}"), ("refs.bib", b"@book{x}")])), pdf: ("notes.pdf", b"%PDF-1.4")}
    report = fetch_attachments(f"{url} and {pdf}", lambda u: fetched[u])
    assert sorted(a.name for a in report.files) == ["main.tex", "notes.pdf", "refs.bib"] and not report.errors
    assert fetch_attachments(url, None).errors == ["1 attachment(s) not fetched in this run"]


def test_attachment_lands_in_the_candidate(research):
    gh = FakeGitHub(research.root)
    url = "https://github.com/user-attachments/files/9/proof.pdf"
    number = gh.open_issue(AUTHOR, "Attempt: TOP-10", render_form("attempt", {**ATTEMPT, "writeup": f"Full proof attached: {url}"}), labels=["intake", "attempt"])
    snapshot = gh.snapshot(number)
    plan = process(snapshot, research, app_id=APP_ID, now=DAY0, fetch=lambda u: ("proof.pdf", b"%PDF-1.4 test"))
    candidate = plan.outcome.candidate
    assert candidate.ok and "files/attachments/proof.pdf" in candidate.files
    assert check_folder(research.root, candidate.folder, candidate.files).ok


def test_bot_identity_is_by_app_id_not_login(research):
    gh = FakeGitHub(research.root)
    number = gh.open_issue(AUTHOR, "Attempt: TOP-10", render_form("attempt", ATTEMPT), labels=["intake", "attempt"])
    gh.comment_as(number, BOT, '<!-- rp-intake-state v1 {"status":"withdrawn"} -->', DAY0, app_id=None)
    assert load_state(gh.snapshot(number), APP_ID)[0].status == "draft"


def test_new_question_asks_discipline_code_and_about_duplicates(research):
    gh = FakeGitHub(research.root)
    parent = research.problem("TOP-10")
    statement = (parent["folder"] / parent["record"]["statement_artifact"]["path"]).read_text()
    values = {"kind": "New question", "statement": statement, "motivation": "Natural.", "checks": "Searched.", "models": "none"}
    number = gh.open_issue(AUTHOR, "Problem: a question", render_form("problem", values), labels=["intake", "problem"])
    plan = run(gh, number, research)
    assert [q["key"] for q in plan.state.questions] == ["discipline"]
    gh.comment_as(number, AUTHOR, "Mathematics", "2026-10-12T01:00:00Z")
    assert [q["key"] for q in run(gh, number, research).state.questions] == ["classification"]
    gh.comment_as(number, AUTHOR, "not-a-code", "2026-10-12T02:00:00Z")
    plan = run(gh, number, research)
    assert plan.state.questions[0]["key"] == "classification" and "is not one" in plan.state.questions[0]["text"]
    gh.comment_as(number, AUTHOR, "11B13", "2026-10-12T03:00:00Z")
    plan = run(gh, number, research)
    assert [q["key"] for q in plan.state.questions] == ["duplicates"] and parent["path"] in plan.state.questions[0]["text"]
    gh.comment_as(number, AUTHOR, "It asks for the sharp constant, not existence.", "2026-10-12T04:00:00Z")
    plan = run(gh, number, research)
    assert plan.state.status == "queued", (plan.state.questions, plan.outcome.candidate and plan.outcome.candidate.report.render())
    assert plan.outcome.candidate.record["classifications"] == [{"scheme": "msc2020", "code": "11B13"}]
    assert plan.outcome.candidate.record["proposal"]["relation_to_known"].endswith("Difference from similar problems: It asks for the sharp constant, not existence.")
