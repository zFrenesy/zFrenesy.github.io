"""Build a small synthetic legacy repository with real Git history (no legacy text).

It mirrors the legacy layout, headers and catalogue formats closely enough to
exercise every importer path: each file class, _v2 siblings, REVISION_OF, a
reused write-up, an openai summary, a human contribution, an odd filename, a
statement-only copy, and a review file edited and then deleted.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Legacy Owner",
    "GIT_AUTHOR_EMAIL": "owner@example.org",
    "GIT_COMMITTER_NAME": "Legacy Owner",
    "GIT_COMMITTER_EMAIL": "owner@example.org",
}

TOP_META = {"category_id": 2, "category": {"id": 2, "name": "combinatorics", "display_name": "Combinatorics", "description": "x", "slug": "combinatorics", "order_index": 2, "created_at": "2026-07-31T15:26:25.671Z"}, "status": "open"}


def _git(repo: Path, *args: str, date: str) -> str:
    env = {**ENV, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env).stdout.strip()


def _write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(repo: Path, message: str, date: str) -> str:
    _git(repo, "add", "-A", date=date)
    _git(repo, "commit", "-q", "-m", message, date=date)
    return _git(repo, "rev-parse", "HEAD", date=date)


def numbered_statement(title: str) -> str:
    return (
        "\\documentclass{article}\n\\newcommand{\\RR}{\\mathbb{R}}\n\\begin{document}\n\\section*{" + title + "}\n"
        "\\subsection{Definitions and mathematical statement}\nLet $x \\in \\RR$ be synthetic.\n"
        "\\subsection{Short English statement}\nIs every synthetic $x$ positive?\n"
        "\\subsection{Sources}\n\\begin{itemize}\n\\item[S1] Synthetic source. \\url{https://example.org/s1}\n\\end{itemize}\n"
        "\\end{document}\n"
    )


def economics_statement(ident: str) -> str:
    return (
        f'% ECONOMICS_PROBLEM: {{"id":"{ident}","title":"Synthetic economics problem {ident}","jel_code":"C73","source_id":"OP-0001"}}\n'
        "% BEGIN ECONOMICS STATEMENT\n\\subsection*{Statement}\n{\\sffamily Find an equilibrium $x$.}\n% END ECONOMICS STATEMENT\n"
    )


def economics_attempt(ident: str, status: str, extra: str = "") -> str:
    return (
        f'% ECONOMICS_PROBLEM: {{"id":"{ident}","title":"Synthetic economics problem {ident}","jel_code":"C73","source_id":"OP-0001"}}\n'
        f"% FIRST_POSTED: 2026-10-09\n% ATTEMPT_STATUS: {status}\n% ENTRY_KIND: research_attempt\n{extra}"
        "\\documentclass{article}\n\\title{Synthetic attempt}\n\\begin{document}\n\\maketitle\nWe study $x$.\n\\end{document}\n"
    )


def build_legacy_repo(root: Path) -> tuple[Path, str]:
    """Create the repository; returns (path, pinned commit)."""
    repo = root / "legacy"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main", date="2026-01-01T00:00:00Z")
    top_ids = ["10", "30007097", "30006001"]
    _write(repo, "lists/erdos_status.json", json.dumps({
        "source_commit": "a" * 40, "checked_at": "2026-09-23T17:22:24Z",
        "problems": {"1": {"status": "proved (Lean)", "status_updated": "2026-09-03"}, "5": {"status": "open"}},
    }))
    _write(repo, "lists/erdos_problems.csv", "number,status,problem_url\n1,x,https://www.erdosproblems.com/1\n5,x,https://www.erdosproblems.com/5\n")
    _write(repo, "lists/mo_problems.csv", "question_id,title,score,tags,creation_date,last_activity_date,last_edit_date,link\n"
           "339137,Synthetic MO &amp; question,10,nt.number-theory;pr.probability,x,x,x,https://mathoverflow.net/questions/339137/x\n")
    _write(repo, "lists/unsolvedmath/problems.json", json.dumps([
        {"id": 10, "problem_number": "OWR-010", "title": "Synthetic OWR problem", **TOP_META, "external_url": "https://www.unsolvedmath.com/problems/OWR-010", "legacy_ids": ["problem.synthetic-owr"], "statement": "Summary."},
        {"id": 30007097, "problem_number": "ALG-002", "title": "Synthetic human problem", **TOP_META, "external_url": None, "legacy_ids": [], "statement": "Summary."},
        {"id": 30006001, "problem_number": "LOCAL-30006001", "title": "Synthetic local problem", **{**TOP_META, "category": {**TOP_META["category"], "slug": "computer-science"}}, "external_url": None, "legacy_ids": [], "statement": "Summary."},
    ]))
    _write(repo, "lists/economics/problems.json", json.dumps({"problems": [
        {"id": "C73-1", "title": "Synthetic economics problem C73-1", "jel_code": "C73", "source_id": "OP-0001", "source_catalog": "Supplement", "initial_rank": 1},
    ]}))
    _write(repo, "lists/openai_math/manifest.json", json.dumps({"source_commit": "b" * 40, "families": []}))
    for ident in top_ids:
        _write(repo, f"attacks/open_problems/top_problems/definitions/{ident}.tex",
               f'% TOP_PROBLEM: {{"id": {ident}}}\n% FIRST_POSTED: 2026-09-25\n% ENTRY_KIND: statement_only\n' + numbered_statement(f"Problem {ident}"))
    _write(repo, "attacks/open_problems/economics/statements/C73-1.tex", economics_statement("C73-1"))
    _write(repo, "README.md", "Synthetic legacy repository.\n")
    _write(repo, "reviews/erdos/5.json", json.dumps({"status": "known", "label": "known", "note": "Known result.", "citations": [],
                                                    "reviewed_by": "reviewer-a", "reviewed_at": "2026-01-20", "issue_number": "26",
                                                    "issue_url": "https://github.com/x/y/issues/26"}))
    _write(repo, "reviews/erdos/1.json", json.dumps({"status": "incorrect", "label": "incorrect", "note": "Wrong.", "citations": [], "reviewed_by": "reviewer-b"}))
    _commit(repo, "Catalogue", "2026-01-15T10:00:00Z")

    # Erdős attempts arrive under the old attacks/erdos/ path and later move.
    _write(repo, "attacks/erdos/gpt_pro_5.2/5.tex", "\\section*{Attempt}\nWe prove the claim for $n \\le 3$.\n")
    _commit(repo, "Old layout attempt", "2026-01-16T09:00:00Z")
    old = repo / "attacks/erdos/gpt_pro_5.2/5.tex"
    _write(repo, "attacks/open_problems/erdos/gpt_pro_5.2/5.tex", old.read_text())
    old.unlink()
    _write(repo, "reviews/erdos/5.json", json.dumps({"status": "known", "label": "known", "note": "Known result (edited).", "citations": [],
                                                    "reviewed_by": "reviewer-a", "reviewed_at": "2026-01-21", "issue_number": "26",
                                                    "issue_url": "https://github.com/x/y/issues/26"}))
    (repo / "reviews/erdos/1.json").unlink()
    _commit(repo, "Move attempts; edit and delete reviews", "2026-01-20T12:00:00Z")

    _write(repo, "attacks/open_problems/erdos/gpt_pro_5.2/5_v2.tex", "% FIRST_POSTED: 2026-02-01\n% ATTEMPT_STATUS: partial\nSecond attack on $n=4$.\n")
    _write(repo, "attacks/open_problems/erdos/GPT_6_Astra_Ultra/1.tex",
           '% COLLECTION_METADATA: {"schema_version": 1, "kind": "reused_writeup", "independently_reviewed": false, '
           '"primary_source": "attacks/erdos/gpt_pro_5.2/5.tex", "source_paths": ["attacks/erdos/gpt_pro_5.2/5.tex"], '
           '"source_model": "gpt_pro_5.2", "source_completion": 40, "source_claim": "unresolved"}\nReused text.\n')
    _write(repo, "attacks/open_problems/erdos/GPT_6_Astra_Ultra/3_2.tex", "Odd filename.\n")
    _write(repo, "attacks/open_problems/economics/gpt_6_astra_pro/C73-1.tex", economics_attempt("C73-1", "unresolved"))
    _write(repo, "attacks/open_problems/economics/gpt_6_astra_pro/C73-1_v2.tex",
           economics_attempt("C73-1", "solved", "% REVISION_OF: gpt_6_astra_pro/C73-1.tex\n"))
    _write(repo, "attacks/open_problems/mo/gpt_pro_5.2/339137 - Synthetic question.tex", "% FIRST_POSTED: 2026-02-02\n% ATTEMPT_STATUS: unresolved\nMO attempt.\n")
    _write(repo, "attacks/open_problems/top_problems/gpt_6_astra_ultra/10.tex",
           '% TOP_PROBLEM: {"id": 10}\n% FIRST_POSTED: 2026-09-26\n% ATTEMPT_STATUS: solved\n% MODEL: GPT 6 Astra Ultra\n'
           "\\documentclass{article}\n\\begin{document}\nA full solution $x>0$.\n\\end{document}\n")
    _write(repo, "attacks/open_problems/top_problems/gpt_6_astra_pro/30006001.tex",
           '% TOP_PROBLEM: {"id": 30006001}\n% FIRST_POSTED: null\n% ENTRY_KIND: statement_only\n' + numbered_statement("Copy"))
    _write(repo, "attacks/open_problems/top_problems/openai/10.tex",
           '% TOP_PROBLEM: {"id": 10}\n% FIRST_POSTED: 2026-10-06\n% ATTEMPT_STATUS: unresolved\n'
           '% OPENAI_CLAIM: {"schema_version":1,"source_commit":"' + "b" * 40 + '","release_date":"2026-10-06","match":"partial","families":[{"title":"Family"}]}\n'
           "\\section*{Claim}\nSummary.\n\\subsection*{Scope relative to this problem}\nOnly $n=2$.\n")
    _write(repo, "attacks/open_problems/top_problems/Human_Contribution/30007097.tex",
           '% TOP_PROBLEM: {"id": 30007097}\n% FIRST_POSTED: 2026-10-10\n% ATTEMPT_STATUS: unresolved\n% ENTRY_KIND: human_contribution\n'
           "\\section*{Human Contribution: Synthetic Author}\nSummary of external work.\n")
    _write(repo, "attacks/open_problems/erdos/gpt_pro_5.4/IMPORTS.md", "Import notes.\n")
    commit = _commit(repo, "Attempts", "2026-10-10T19:58:16Z")
    return repo, commit


SNAPSHOT = {
    "schema_version": 1,
    "repository": "mehmetmars7/Erdosproblems-llm-hunter",
    "repository_id": 1136156171,
    "users": {"mehmetmars7": {"id": 243585043}, "reviewer-a": {"id": 1001}, "shea256": {"id": 994646}},
    "issues": {"26": {"author": "reviewer-a", "labelled": [{"label": "review", "actor": "mehmetmars7", "at": "2026-01-20T12:00:00Z"}]}},
    "unavailable": [],
}
