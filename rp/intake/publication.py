"""Execute an intake plan: comments, labels and managed publication PRs (spec §6, §9).

One path for every source. A form candidate becomes a bot commit on the bot-owned
branch ``intake/issue-<n>``. A fork pull request is incorporated: the bot-owned
branch ``intake/pr-<n>`` points at the contributor's own head commit, so their
commits and authorship are carried unchanged, and the original pull request is
closed as "incorporated", never shown as merged. Nothing here merges; publication
PRs wait for the milestone 4 gate and the milestone 5 publisher.

Every action is idempotent: messages carry a hidden key and are posted once,
branches and pull requests are looked up before they are created, and the state
comment is written last.
"""

from __future__ import annotations

from typing import Protocol

from rp.intake.engine import Action, Plan
from rp.intake.snapshot import Comment, IntakeSnapshot
from rp.intake.state import render_state

__all__ = ["GitHubPort", "STATUS_LABEL", "apply_plan", "message_key"]

STATUS_LABEL = "intake: "
_KEY = "<!-- rp-intake-msg {} -->"


def message_key(key: str) -> str:
    return _KEY.format(key.replace("--", "- -"))


class GitHubPort(Protocol):
    repository: str

    def comments(self, number: int) -> list[Comment]: ...
    def create_comment(self, number: int, body: str) -> int: ...
    def update_comment(self, comment_id: int, body: str) -> None: ...
    def set_labels(self, number: int, add: list[str], remove: list[str]) -> None: ...
    def set_state(self, number: int, state: str, reason: str | None = None) -> None: ...
    def branch_sha(self, branch: str) -> str | None: ...
    def set_branch(self, branch: str, sha: str) -> None: ...
    def commit_files(self, parent: str, files: dict[str, bytes], message: str) -> str: ...
    def tree_matches(self, sha: str, files: dict[str, bytes]) -> bool: ...
    def find_pull(self, branch: str) -> int | None: ...
    def create_pull(self, branch: str, base: str, title: str, body: str) -> int: ...


def _post(port: GitHubPort, snapshot: IntakeSnapshot, existing: list[Comment], app_id: int, key: str, body: str) -> None:
    marker = message_key(key)
    if any(c.app_id == app_id and marker in c.body for c in existing):
        return
    port.create_comment(snapshot.number, f"{body.rstrip()}\n\n{marker}")


def _publish(port: GitHubPort, snapshot: IntakeSnapshot, action: Action, plan: Plan, base: str) -> None:
    params = action.params
    files = {f"{params['folder']}/{name}": content for name, (content, _mode) in params["files"].items()}
    branch = params["branch"]
    current = port.branch_sha(branch)
    if current is None or not port.tree_matches(current, files):
        parent = port.branch_sha(base)
        if parent is None:
            raise RuntimeError(f"base branch {base} not found")
        sha = port.commit_files(parent, files, f"Add submission from #{snapshot.number}")
        port.set_branch(branch, sha)
    number = port.find_pull(branch)
    if number is None:
        body = (f"Publication candidate for #{snapshot.number}, submitted by @{snapshot.author.login} (GitHub ID {snapshot.author.id}).\n\n"
                f"Folder: `{params['folder']}`\nCandidate digest: `{params['digest']}`\n\n"
                "Queued for screening and publication; nothing is merged by hand.")
        number = port.create_pull(branch, base, params["title"][:200], body)
    plan.state.publication_pr = number


def _incorporate(port: GitHubPort, snapshot: IntakeSnapshot, action: Action, plan: Plan, base: str, existing: list[Comment], app_id: int) -> None:
    params = action.params
    branch = params["branch"]
    if port.branch_sha(branch) != params["head_sha"]:
        # The contributor's own commits, unchanged: same objects, same authors, same committers.
        port.set_branch(branch, params["head_sha"])
    number = port.find_pull(branch)
    if number is None:
        body = (f"Publication candidate incorporating #{params['source_pr']} by @{params['author']['login']} "
                f"(GitHub ID {params['author']['id']}). The contributor's commits are carried unchanged.\n\n"
                f"Source head: `{params['head_sha']}`\nFolder: `{params['folder']}`\nCandidate digest: `{params['digest']}`\n\n"
                "Queued for screening and publication; nothing is merged by hand.")
        number = port.create_pull(branch, base, params["title"][:200], body)
    plan.state.publication_pr = number
    _post(port, snapshot, existing, app_id, f"incorporated:{number}",
          f"Incorporated into #{number}, which carries your commits unchanged. This pull request is closed as incorporated, not merged.")
    if snapshot.state == "open":
        port.set_state(snapshot.number, "closed")


def apply_plan(plan: Plan, port: GitHubPort, snapshot: IntakeSnapshot, *, app_id: int, base: str = "main") -> None:
    existing = port.comments(snapshot.number)
    for action in plan.actions:
        if action.kind == "comment":
            _post(port, snapshot, existing, app_id, action.params["key"], action.params["body"])
        elif action.kind == "publish":
            _publish(port, snapshot, action, plan, base)
        elif action.kind == "incorporate":
            _incorporate(port, snapshot, action, plan, base, existing, app_id)
        elif action.kind == "close":
            port.set_state(snapshot.number, "closed", action.params.get("reason"))
        elif action.kind == "reopen":
            port.set_state(snapshot.number, "open")
        elif action.kind == "labels":
            wanted = STATUS_LABEL + action.params["status"]
            stale = [label for label in snapshot.labels if label.startswith(STATUS_LABEL) and label != wanted]
            if wanted not in snapshot.labels or stale:
                port.set_labels(snapshot.number, [wanted], stale)
        else:
            raise ValueError(f"unknown intake action {action.kind}")
    state = plan.state
    summary = f"Status: {state.status}." + (f" Publication pull request: #{state.publication_pr}." if state.publication_pr else "")
    body = render_state(state, summary)
    holder = next((c for c in reversed(existing) if c.app_id == app_id and "<!-- rp-intake-state v1 " in c.body), None)
    if holder is None:
        port.create_comment(snapshot.number, body)
    elif holder.body != body:
        port.update_comment(holder.id, body)
