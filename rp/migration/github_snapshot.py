"""Read-only GitHub snapshot for the legacy migration.

    python -m rp.migration.github_snapshot --legacy <path-to-legacy-clone>

Uses ``gh api`` with GET requests only (the owner's login) to record the
legacy repository's numeric ID, the numeric IDs of referenced users, and the
author and labelling events of the review issues. The snapshot is committed
(``rp/migration/legacy/github-snapshot.json``) so re-imports never need the
network. Any read that fails is recorded as unavailable; the importer then
marks the affected fields ``unknown`` (docs/adr/0010).
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from rp.migration.legacy_git import LegacyRepo, LEGACY_COMMIT
from rp.migration.reviews import review_history

SNAPSHOT_PATH = Path(__file__).resolve().parent / "legacy" / "github-snapshot.json"
LEGACY_REPOSITORY = "mehmetmars7/Erdosproblems-llm-hunter"


def gh_get(path: str) -> Any:
    if not path.startswith("/") or "://" in path:
        raise ValueError(f"refusing to fetch {path!r}")
    proc = subprocess.run(
        ["gh", "api", "--method", "GET", "-H", "Accept: application/vnd.github+json", path],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip()[:300] or f"gh api {path} failed")
    return json.loads(proc.stdout)


def _try(path: str, unavailable: list[str]) -> Any:
    try:
        return gh_get(path)
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        unavailable.append(f"{path}: {exc}")
        return None


def build_snapshot(repo: LegacyRepo) -> dict[str, Any]:
    histories = review_history(repo)
    logins: set[str] = {"mehmetmars7"}
    issues: set[int] = set()
    for history in histories.values():
        for version in history.versions:
            logins.update(version.logins())
            if version.issue_number:
                issues.add(version.issue_number)
    unavailable: list[str] = []
    repository = _try(f"/repos/{LEGACY_REPOSITORY}", unavailable)
    snapshot: dict[str, Any] = {
        "schema_version": 1,
        "repository": LEGACY_REPOSITORY,
        "repository_id": repository.get("id") if repository else None,
        "legacy_commit": LEGACY_COMMIT,
        "users": {},
        "issues": {},
        "unavailable": unavailable,
    }
    for number in sorted(issues):
        issue = _try(f"/repos/{LEGACY_REPOSITORY}/issues/{number}", unavailable)
        events = _try(f"/repos/{LEGACY_REPOSITORY}/issues/{number}/events?per_page=100", unavailable)
        if issue is None:
            continue
        labelled = [
            {"label": e["label"]["name"], "actor": (e.get("actor") or {}).get("login"), "at": e.get("created_at")}
            for e in (events or [])
            if e.get("event") == "labeled" and e.get("label")
        ]
        snapshot["issues"][str(number)] = {
            "author": (issue.get("user") or {}).get("login"),
            "created_at": issue.get("created_at"),
            "closed_at": issue.get("closed_at"),
            "labels": sorted(label["name"] for label in issue.get("labels", [])),
            "labelled": labelled if events is not None else None,
        }
        for login in [snapshot["issues"][str(number)]["author"], *[x["actor"] for x in labelled]]:
            if login:
                logins.add(login)
    for login in sorted(logins):
        user = _try(f"/users/{login}", unavailable)
        snapshot["users"][login] = {"id": user.get("id") if user else None, "type": user.get("type") if user else None}
    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only GitHub snapshot for the legacy migration")
    parser.add_argument("--legacy", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=SNAPSHOT_PATH)
    args = parser.parse_args()
    snapshot = build_snapshot(LegacyRepo(args.legacy))
    args.out.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.out} ({len(snapshot['users'])} users, {len(snapshot['issues'])} issues, {len(snapshot['unavailable'])} unavailable)")


if __name__ == "__main__":
    main()
