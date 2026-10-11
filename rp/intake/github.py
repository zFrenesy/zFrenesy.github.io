"""Read GitHub through the ``gh`` CLI, for the maintainer's dry run (``rp intake dry-run``).

``GhReadOnly`` builds the same snapshots the intake App will build and implements
the ``GitHubPort`` reads; every write is only recorded and printed. It uses the
maintainer's own ``gh`` login and never changes anything on GitHub.
"""

from __future__ import annotations

import base64
import json
import subprocess
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from rp.contribute.check import LIMITS
from rp.intake.snapshot import PR_FILES_CAP, Actor, ChangedFile, Comment, IncompleteListing, IntakeSnapshot, collect_pages

__all__ = ["GhApi", "GhLive", "GhReadOnly"]

PER_PAGE = 100


class GhApi:
    def __init__(self, runner: Callable = subprocess.run):
        self.runner = runner

    def get(self, path: str) -> Any:
        proc = self.runner(["gh", "api", "-H", "Accept: application/vnd.github+json", path], capture_output=True, text=True)
        if proc.returncode != 0:
            if "404" in (proc.stderr or ""):
                return None
            raise RuntimeError(f"gh api {path}: {(proc.stderr or '').strip()[:300]}")
        return json.loads(proc.stdout)

    def pages(self, path: str) -> list[list[Any]]:
        sep = "&" if "?" in path else "?"
        proc = self.runner(["gh", "api", "--paginate", "--slurp", f"{path}{sep}per_page={PER_PAGE}"], capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"gh api {path}: {(proc.stderr or '').strip()[:300]}")
        return json.loads(proc.stdout)


def _comment(item: dict) -> Comment:
    app = item.get("performed_via_github_app") or {}
    return Comment(item["id"], Actor(item["user"]["login"], item["user"]["id"]), item.get("body") or "", item["created_at"], app.get("id"))


class GhReadOnly:
    def __init__(self, repository: str, api: GhApi | None = None, out: Callable[[str], None] = print):
        self.repository, self.api, self.out = repository, api or GhApi(), out
        self.log: list[str] = []
        self._trees: dict[str, dict[str, dict]] = {}

    # snapshots ------------------------------------------------------------------
    def maintainers(self) -> frozenset[int]:
        try:
            people = [p for page in self.api.pages(f"repos/{self.repository}/collaborators") for p in page]
        except RuntimeError:
            return frozenset()
        return frozenset(p["id"] for p in people if p.get("permissions", {}).get("maintain") or p.get("permissions", {}).get("admin"))

    def _comments(self, number: int, expected: int) -> tuple[Comment, ...]:
        pages = self.api.pages(f"repos/{self.repository}/issues/{number}/comments")
        return tuple(_comment(c) for c in collect_pages(pages, expected=expected, per_page=PER_PAGE))

    def snapshot_issue(self, number: int) -> IntakeSnapshot:
        issue = self.api.get(f"repos/{self.repository}/issues/{number}")
        if issue is None:
            raise RuntimeError(f"{self.repository}#{number} not found")
        return IntakeSnapshot(
            self.repository, "pull_request" if issue.get("pull_request") else "issue", number, issue["state"],
            Actor(issue["user"]["login"], issue["user"]["id"]), issue["title"], issue.get("body") or "", issue["created_at"],
            tuple(label["name"] for label in issue.get("labels", [])), self._comments(number, issue["comments"]),
            maintainers=self.maintainers(),
        )

    def _tree_entry(self, repository: str, commit: str, path: str) -> dict:
        """The tree entry for ``path`` at ``commit``, walking one directory level per request (no truncation)."""
        sha = commit
        parts = path.split("/")
        for depth, part in enumerate(parts):
            key = f"{repository}:{sha}"
            if key not in self._trees:
                tree = self.api.get(f"repos/{repository}/git/trees/{sha}")
                if tree is None or tree.get("truncated"):
                    raise IncompleteListing(f"tree listing for {'/'.join(parts[:depth]) or '/'} is incomplete")
                self._trees[key] = {entry["path"]: entry for entry in tree["tree"]}
            entry = self._trees[key].get(part)
            if entry is None:
                raise IncompleteListing(f"{path} is not in the head tree")
            if depth == len(parts) - 1:
                return entry
            sha = entry["sha"]
        raise IncompleteListing(path)

    def snapshot_pull(self, number: int) -> tuple[IntakeSnapshot, dict[str, bytes]]:
        issue = self.snapshot_issue(number)
        pull = self.api.get(f"repos/{self.repository}/pulls/{number}")
        head_repo = pull["head"]["repo"]["full_name"] if pull["head"].get("repo") else self.repository
        listed = collect_pages(self.api.pages(f"repos/{self.repository}/pulls/{number}/files"),
                               expected=pull["changed_files"], per_page=PER_PAGE, cap=PR_FILES_CAP)
        files, blobs, total = [], {}, 0
        for item in listed:
            mode, content = "000000", b""
            if item["status"] != "removed":
                entry = self._tree_entry(head_repo, pull["head"]["sha"], item["filename"])
                mode = entry["mode"]
                if entry["type"] == "blob" and mode in ("100644", "100755"):
                    total += entry.get("size", 0)
                    if total > LIMITS["total_bytes"]:
                        raise IncompleteListing("the pull request is larger than the 25 MiB limit")
                    blob = self.api.get(f"repos/{head_repo}/git/blobs/{entry['sha']}")
                    content = base64.b64decode(blob["content"]) if blob else b""
            files.append(ChangedFile(item["filename"], item["status"], item["sha"], len(content), mode, item.get("previous_filename")))
            blobs[item["filename"]] = content
        snapshot = IntakeSnapshot(
            issue.repository, "pull_request", number, issue.state, issue.author, issue.title, issue.body, issue.created_at,
            issue.labels, issue.comments, pull["head"]["sha"], pull["base"]["sha"], head_repo, tuple(files), issue.maintainers)
        return snapshot, blobs

    # GitHubPort: reads -------------------------------------------------------------
    def comments(self, number: int) -> list[Comment]:
        issue = self.api.get(f"repos/{self.repository}/issues/{number}")
        return list(self._comments(number, issue["comments"]))

    def branch_sha(self, branch: str) -> str | None:
        ref = self.api.get(f"repos/{self.repository}/git/ref/heads/{branch}")
        return ref["object"]["sha"] if ref else None

    def tree_matches(self, sha: str, files: dict[str, bytes]) -> bool:
        return False

    def find_pull(self, branch: str) -> int | None:
        owner = self.repository.split("/")[0]
        pulls = self.api.get(f"repos/{self.repository}/pulls?state=all&head={owner}:{branch}")
        return pulls[0]["number"] if pulls else None

    # GitHubPort: writes are recorded only ------------------------------------------
    def _record(self, text: str) -> None:
        self.log.append(text)
        self.out("would " + text)

    def create_comment(self, number: int, body: str) -> int:
        self._record(f"comment on #{number}:\n" + "\n".join("    " + line for line in body.splitlines()))
        return 0

    def update_comment(self, comment_id: int, body: str) -> None:
        self._record(f"update the state comment {comment_id}")

    def set_labels(self, number: int, add: list[str], remove: list[str]) -> None:
        self._record(f"label #{number}: add {add}, remove {remove}")

    def set_state(self, number: int, state: str, reason: str | None = None) -> None:
        self._record(f"set #{number} {state}" + (f" ({reason})" if reason else ""))

    def set_branch(self, branch: str, sha: str) -> None:
        self._record(f"point branch {branch} at {sha}")

    def commit_files(self, parent: str, files: dict[str, bytes], message: str) -> str:
        self._record(f"commit {len(files)} file(s) on {parent[:12]}: " + ", ".join(sorted(files)))
        return "0" * 40

    def create_pull(self, branch: str, base: str, title: str, body: str) -> int:
        self._record(f"open a publication pull request {branch} -> {base}: {title}")
        return 0


class GhLive(GhReadOnly):
    """Writes through ``gh api`` with the intake App's installation token (``GH_TOKEN``). Used only by intake.yml."""

    def __init__(self, repository: str, api: GhApi | None = None, out: Callable[[str], None] = print,
                 runner: Callable = subprocess.run):
        super().__init__(repository, api, out)
        self.runner = runner

    def _call(self, method: str, path: str, payload: dict | None = None) -> Any:
        proc = self.runner(["gh", "api", "--method", method, "-H", "Accept: application/vnd.github+json", path, "--input", "-"],
                           input=json.dumps(payload or {}), capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"gh api {method} {path}: {(proc.stderr or '').strip()[:300]}")
        return json.loads(proc.stdout) if proc.stdout.strip() else None

    def create_comment(self, number: int, body: str) -> int:
        return self._call("POST", f"repos/{self.repository}/issues/{number}/comments", {"body": body})["id"]

    def update_comment(self, comment_id: int, body: str) -> None:
        self._call("PATCH", f"repos/{self.repository}/issues/comments/{comment_id}", {"body": body})

    def set_labels(self, number: int, add: list[str], remove: list[str]) -> None:
        for label in remove:
            self._call("DELETE", f"repos/{self.repository}/issues/{number}/labels/{quote(label, safe='')}")
        if add:
            self._call("POST", f"repos/{self.repository}/issues/{number}/labels", {"labels": add})

    def set_state(self, number: int, state: str, reason: str | None = None) -> None:
        payload = {"state": state, **({"state_reason": reason} if reason else {})}
        self._call("PATCH", f"repos/{self.repository}/issues/{number}", payload)

    def set_branch(self, branch: str, sha: str) -> None:
        if self.branch_sha(branch) is None:
            self._call("POST", f"repos/{self.repository}/git/refs", {"ref": f"refs/heads/{branch}", "sha": sha})
        else:
            # Only bot-owned intake/* branches are ever moved.
            if not branch.startswith("intake/"):
                raise RuntimeError(f"refusing to move {branch}")
            self._call("PATCH", f"repos/{self.repository}/git/refs/heads/{branch}", {"sha": sha, "force": True})

    def commit_files(self, parent: str, files: dict[str, bytes], message: str) -> str:
        base_tree = self.api.get(f"repos/{self.repository}/git/commits/{parent}")["tree"]["sha"]
        entries = []
        for path, content in sorted(files.items()):
            blob = self._call("POST", f"repos/{self.repository}/git/blobs", {"content": base64.b64encode(content).decode(), "encoding": "base64"})
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        tree = self._call("POST", f"repos/{self.repository}/git/trees", {"base_tree": base_tree, "tree": entries})
        return self._call("POST", f"repos/{self.repository}/git/commits", {"message": message, "tree": tree["sha"], "parents": [parent]})["sha"]

    def tree_matches(self, sha: str, files: dict[str, bytes]) -> bool:
        for path, content in files.items():
            item = self.api.get(f"repos/{self.repository}/contents/{quote(path)}?ref={sha}")
            if not item or item.get("type") != "file" or base64.b64decode(item.get("content", "")) != content:
                return False
        return True

    def create_pull(self, branch: str, base: str, title: str, body: str) -> int:
        return self._call("POST", f"repos/{self.repository}/pulls", {"head": branch, "base": base, "title": title, "body": body})["number"]
