"""The gh-based adapters: complete listings, tree walking, and writes that only touch intake branches."""

import base64
import json
from types import SimpleNamespace

import pytest

from rp.intake.github import GhApi, GhLive, GhReadOnly
from rp.intake.snapshot import IncompleteListing

REPO = "we-solve-staging/research"
HEAD = "h" * 40


class CannedGh:
    def __init__(self, responses):
        self.responses, self.calls = responses, []

    def __call__(self, cmd, capture_output=True, text=True, input=None):
        self.calls.append((cmd, input))
        path = next(a for a in cmd[2:] if a.startswith("repos/"))
        key = path.split("?")[0] if "--paginate" in cmd else path
        if key not in self.responses:
            return SimpleNamespace(returncode=1, stdout="", stderr="HTTP 404 Not Found")
        return SimpleNamespace(returncode=0, stdout=json.dumps(self.responses[key]), stderr="")


def issue(comments=1, **extra):
    return {"number": 4, "state": "open", "title": "Attempt: TOP-10", "body": "### Problem handle\n\nTOP-10\n",
            "user": {"login": "contributor-x", "id": 424242}, "created_at": "2026-10-12T00:00:00Z", "labels": [{"name": "intake"}],
            "comments": comments, **extra}


def comment(cid, app=None):
    return {"id": cid, "user": {"login": "x", "id": 1}, "body": "hi", "created_at": "2026-10-12T01:00:00Z",
            "performed_via_github_app": {"id": app} if app else None}


def test_issue_snapshot_reads_app_ids_and_requires_complete_comments():
    responses = {f"repos/{REPO}/issues/4": issue(comments=2), f"repos/{REPO}/issues/4/comments": [[comment(1), comment(2, app=777)]],
                 f"repos/{REPO}/collaborators": [[{"id": 7, "permissions": {"maintain": True}}, {"id": 8, "permissions": {"push": True}}]]}
    snapshot = GhReadOnly(REPO, GhApi(CannedGh(responses))).snapshot_issue(4)
    assert [c.app_id for c in snapshot.comments] == [None, 777] and snapshot.maintainers == frozenset({7})
    responses[f"repos/{REPO}/issues/4"] = issue(comments=3)
    with pytest.raises(IncompleteListing):
        GhReadOnly(REPO, GhApi(CannedGh(responses))).snapshot_issue(4)


def test_pull_snapshot_walks_trees_for_modes_and_reads_blobs():
    path = "problems/ab/prb_x/contributions/con_y/files/run.md"
    tree = lambda name, sha, kind="tree", mode="040000": {"path": name, "sha": sha, "type": kind, "mode": mode, "size": 4}
    responses = {
        f"repos/{REPO}/issues/5": issue(comments=0, pull_request={}), f"repos/{REPO}/issues/5/comments": [[]],
        f"repos/{REPO}/collaborators": [[]],
        f"repos/{REPO}/pulls/5": {"changed_files": 1, "head": {"sha": HEAD, "repo": {"full_name": "fork/research"}}, "base": {"sha": "b" * 40}},
        f"repos/{REPO}/pulls/5/files": [[{"filename": path, "status": "added", "sha": "s1"}]],
        f"repos/fork/research/git/trees/{HEAD}": {"tree": [tree("problems", "t1")]},
        "repos/fork/research/git/trees/t1": {"tree": [tree("ab", "t2")]},
        "repos/fork/research/git/trees/t2": {"tree": [tree("prb_x", "t3")]},
        "repos/fork/research/git/trees/t3": {"tree": [tree("contributions", "t4")]},
        "repos/fork/research/git/trees/t4": {"tree": [tree("con_y", "t5")]},
        "repos/fork/research/git/trees/t5": {"tree": [tree("files", "t6")]},
        "repos/fork/research/git/trees/t6": {"tree": [tree("run.md", "blob1", "blob", "100755")]},
        "repos/fork/research/git/blobs/blob1": {"content": base64.b64encode(b"echo").decode()},
    }
    snapshot, blobs = GhReadOnly(REPO, GhApi(CannedGh(responses))).snapshot_pull(5)
    assert snapshot.files[0].mode == "100755" and blobs[path] == b"echo" and snapshot.head_repository == "fork/research"
    responses["repos/fork/research/git/trees/t6"] = {"tree": [], "truncated": True}
    with pytest.raises(IncompleteListing):
        GhReadOnly(REPO, GhApi(CannedGh(responses))).snapshot_pull(5)
    responses[f"repos/{REPO}/pulls/5"]["changed_files"] = 2
    with pytest.raises(IncompleteListing):
        GhReadOnly(REPO, GhApi(CannedGh(responses))).snapshot_pull(5)


def test_dry_run_records_writes_without_sending_them():
    gh = CannedGh({})
    port = GhReadOnly(REPO, GhApi(gh), out=lambda line: None)
    port.create_comment(4, "hello")
    port.set_branch("intake/issue-4", HEAD)
    port.create_pull("intake/issue-4", "main", "T", "B")
    assert len(port.log) == 3 and gh.calls == []


def test_live_port_moves_only_intake_branches():
    gh = CannedGh({f"repos/{REPO}/git/ref/heads/main": {"object": {"sha": HEAD}}})
    port = GhLive(REPO, GhApi(gh), runner=gh)
    with pytest.raises(RuntimeError, match="refusing to move main"):
        port.set_branch("main", "c" * 40)
