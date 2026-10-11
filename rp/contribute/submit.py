"""``rp submit``: open a pull request from the contributor's own account (spec §6, §20).

Uses the contributor's ``git`` identity (so commit authorship is theirs) and their
``gh`` login. Every command is an argument list, never a shell string, and
``--dry-run`` prints exactly what would run. Legal declarations (rights, public
disclosure, LLM disclosure) are confirmed only by a person at an interactive
terminal; an agent's ``--yes`` never confirms them on the person's behalf.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from rp import strict_yaml
from rp.contribute.check import CheckReport, changed_paths, check_changes

__all__ = ["SubmitPlan", "plan_submission", "submit"]

DECLARATION_QUESTIONS = {
    "rights": "I have the right to publish this material under CC BY 4.0 (software: Apache-2.0), and third-party material is credited.",
    "public_disclosure": "I understand that the pull request and its contents are public immediately.",
    "ai_disclosure": "Every LLM and person involved is listed, with versions or 'unknown'.",
}


@dataclass
class SubmitPlan:
    folder: str
    branch: str
    upstream: str
    head_owner: str
    push_remote: str
    commands: list[list[str]]
    title: str
    body: str


def _run(cmd: Sequence[str], cwd: Path, runner: Callable = subprocess.run) -> str:
    proc = runner(list(cmd), cwd=str(cwd), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:3])} failed: {(proc.stderr or proc.stdout).strip()[:400]}")
    return proc.stdout


def _upstream(root: Path, runner: Callable) -> str:
    """owner/name of the research repository (the 'upstream' remote if present, else 'origin')."""
    remotes = _run(["git", "remote", "-v"], root, runner)
    urls = {}
    for line in remotes.splitlines():
        name, url, *_ = line.split()
        urls[name] = url
    url = urls.get("upstream") or urls.get("origin") or ""
    match = re.search(r"github\.com[:/]([A-Za-z0-9-]+/[A-Za-z0-9._-]+?)(?:\.git)?$", url)
    if not match:
        raise RuntimeError("cannot tell which GitHub repository to submit to; add it as the 'upstream' remote")
    return match.group(1)


def plan_submission(root: Path, report: CheckReport, *, login: str, can_push: bool, upstream: str, fork_remote: str | None) -> SubmitPlan:
    contributions = [f for f in report.folders]
    if len(contributions) != 1:
        raise RuntimeError(f"submit one new folder at a time (found {len(contributions)})")
    folder = contributions[0]
    record_file = "contribution.yaml" if "/contributions/" in folder or "/reviews/" in folder else "problem.yaml"
    record = strict_yaml.load((root / folder / record_file).read_bytes())
    ident = record.get("contribution_id") or record.get("problem_id")
    branch = "contrib/" + ident
    remote = "origin" if can_push else (fork_remote or "fork")
    head_owner = upstream.split("/")[0] if can_push else login
    unconfirmed = [k for k, v in (record.get("declarations") or {}).items() if not v.get("confirmed")]
    body = [
        f"Adds `{folder}`.",
        "",
        f"- Title: {record['title']}",
        f"- Type: {record.get('type') or record.get('kind')}",
    ]
    if record.get("claim"):
        body.append(f"- Claim: {record['claim']['type']}")
    body += ["", "Format checks: `rp check` passed locally; the pull-request check repeats them."]
    if unconfirmed:
        body += ["", "Declarations awaiting the submitter's confirmation: " + ", ".join(unconfirmed) + "."]
    body += ["", "Submissions queue for screening and publication; nothing is merged by hand."]
    commands = [
        ["git", "switch", "-c", branch],
        ["git", "add", "--", folder],
        ["git", "commit", "-m", f"Add {record.get('type') or record.get('kind')} {ident[:12]}"],
    ]
    if not can_push and fork_remote is None:
        commands.append(["gh", "repo", "fork", upstream, "--remote=true", "--remote-name=fork"])
    commands += [
        ["git", "push", "-u", remote, branch],
        ["gh", "pr", "create", "--repo", upstream, "--head", f"{head_owner}:{branch}", "--title", record["title"], "--body", "\n".join(body)],
    ]
    return SubmitPlan(folder, branch, upstream, head_owner, remote, commands, record["title"], "\n".join(body))


def _confirm_declarations(root: Path, folder: str, ask: Callable[[str], str]) -> list[str]:
    path = root / folder / "contribution.yaml"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    header = "".join(line for line in text.splitlines(keepends=True) if line.startswith("#"))
    record = strict_yaml.load(text)
    confirmed = []
    for key, question in DECLARATION_QUESTIONS.items():
        entry = record.get("declarations", {}).get(key)
        if entry and not entry["confirmed"] and ask(f"{question} [y/N] ").strip().lower() in ("y", "yes"):
            entry["confirmed"] = True
            confirmed.append(key)
    if confirmed:
        path.write_text(header + strict_yaml.dump(record), encoding="utf-8")
    return confirmed


def submit(root: Path, *, yes: bool = False, dry_run: bool = False, base: str | None = None,
           runner: Callable = subprocess.run, ask: Callable[[str], str] = input, interactive: bool | None = None,
           out: Callable[[str], None] = print) -> SubmitPlan | None:
    interactive = sys.stdin.isatty() if interactive is None else interactive
    base = base or _default_base(root, runner)
    report = check_changes(root, changed_paths(root, base, None))
    out(report.render())
    if not report.ok:
        raise RuntimeError("fix the errors above, then run rp submit again")
    if interactive and not dry_run:
        _confirm_declarations(root, report.folders[0], ask)
    user = json.loads(_run(["gh", "api", "user"], root, runner))
    upstream = _upstream(root, runner)
    can_push = _run(["gh", "api", f"repos/{upstream}", "--jq", ".permissions.push"], root, runner).strip() == "true"
    remotes = _run(["git", "remote"], root, runner).split()
    plan = plan_submission(root, report, login=user["login"], can_push=can_push, upstream=upstream,
                           fork_remote="fork" if "fork" in remotes else None)
    out("Will run:\n" + "\n".join("  " + " ".join(_quote(a) for a in cmd) for cmd in plan.commands))
    if dry_run:
        return plan
    if not yes and not (interactive and ask(f"Open a pull request to {upstream}? [y/N] ").strip().lower() in ("y", "yes")):
        out("Nothing was pushed.")
        return None
    for cmd in plan.commands:
        out(_run(cmd, root, runner).strip())
    return plan


def _default_base(root: Path, runner: Callable = subprocess.run) -> str | None:
    for ref in ("upstream/main", "origin/main"):
        proc = runner(["git", "rev-parse", "--verify", "--quiet", ref], cwd=str(root), capture_output=True, text=True)
        if proc.returncode == 0:
            return ref
    return None


def _quote(arg: str) -> str:
    return arg if re.fullmatch(r"[A-Za-z0-9_./:@=+-]+", arg) else "'" + arg.replace("'", "'\\''")[:120] + ("…'" if len(arg) > 120 else "'")
