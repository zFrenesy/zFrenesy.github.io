"""Verify GitHub organisation settings against operations/expected-settings.yaml.

    GITHUB_TOKEN=... python -m rp.ops.verify_settings --org we-solve-staging

Owner-run and read-only: it sends GET requests only and changes nothing. The
owner applies settings by following operations/staging-org.md; this tool then
reads them back through the REST API (§0). It fails closed: a field that is
missing from a response, unreadable with the token's permissions, or of an
unexpected shape is a failure, never a pass.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from rp import strict_yaml

API_ROOT = "https://api.github.com"
API_VERSION = "2022-11-28"
DEFAULT_EXPECTED = Path(__file__).resolve().parents[2] / "operations" / "expected-settings.yaml"
MISSING = object()


class Fetcher(Protocol):
    def get(self, path: str) -> tuple[int, Any]: ...


class HttpFetcher:
    """GET-only GitHub REST client."""

    def __init__(self, token: str, timeout: float = 30.0):
        self._token = token
        self._timeout = timeout

    def get(self, path: str) -> tuple[int, Any]:
        if not path.startswith("/") or "://" in path:
            raise ValueError(f"refusing to fetch {path!r}")
        request = urllib.request.Request(
            API_ROOT + path,
            method="GET",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "we-solve-verify-settings",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310 - fixed https host
                return response.status, json.loads(response.read() or b"null")
        except urllib.error.HTTPError as exc:
            return exc.code, None


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


def _dig(data: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        if not isinstance(data, Mapping) or part not in data:
            return MISSING
        data = data[part]
    return data


def _compare(name: str, got: Any, want: Any) -> Check:
    if got is MISSING:
        return Check(name, False, "not present in the API response (check token scope); failing closed")
    if isinstance(want, list):
        ok = isinstance(got, list) and sorted(map(str, got)) == sorted(map(str, want))
    else:
        ok = got == want
    return Check(name, ok, f"expected {want!r}, found {got!r}")


def _fields(fetcher: Fetcher, path: str, prefix: str, expected: Mapping[str, Any], dotted: Mapping[str, str] | None = None) -> list[Check]:
    status, body = fetcher.get(path)
    if status != 200 or not isinstance(body, Mapping):
        return [Check(f"{prefix}.{key}", False, f"GET {path} returned {status}") for key in expected]
    dotted = dotted or {}
    return [_compare(f"{prefix}.{key}", _dig(body, dotted.get(key, key)), want) for key, want in expected.items()]


REPO_FIELDS = {
    "visibility": "visibility",
    "default_branch": "default_branch",
    "secret_scanning": "security_and_analysis.secret_scanning.status",
    "secret_scanning_push_protection": "security_and_analysis.secret_scanning_push_protection.status",
}


def verify(expected: Mapping[str, Any], fetcher: Fetcher, org: str | None = None) -> list[Check]:
    org = org or expected["organisation"]
    checks: list[Check] = []
    checks += _fields(fetcher, f"/orgs/{org}", "org", expected["org"])
    checks += _fields(fetcher, f"/orgs/{org}/actions/permissions", "actions", expected["actions"])
    checks += _fields(fetcher, f"/orgs/{org}/actions/permissions/selected-actions", "selected_actions", expected["selected_actions"])
    checks += _fields(fetcher, f"/orgs/{org}/actions/permissions/workflow", "workflow", expected["workflow"])
    checks += _fields(
        fetcher, f"/orgs/{org}/actions/permissions/fork-pr-contributor-approval", "fork_pr_approval", expected["fork_pr_approval"]
    )
    for template, settings in expected["repositories"].items():
        repo = template.format(org=org)
        fields = {k: v for k, v in settings.items() if k != "branches"}
        checks += _fields(fetcher, f"/repos/{org}/{repo}", f"repo.{repo}", fields, REPO_FIELDS)
        for branch in settings.get("branches", []):
            status, _ = fetcher.get(f"/repos/{org}/{repo}/branches/{branch}")
            checks.append(Check(f"repo.{repo}.branch.{branch}", status == 200, f"GET returned {status}"))
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only check of GitHub settings against the expected configuration.")
    parser.add_argument("--org", help="organisation to check (default: the one in the expected file)")
    parser.add_argument("--expected", type=Path, default=DEFAULT_EXPECTED)
    args = parser.parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN is not set; use a token that can read the organisation's settings.", file=sys.stderr)
        return 2
    expected = strict_yaml.load(args.expected.read_bytes())
    checks = verify(expected, HttpFetcher(token), args.org)
    for check in checks:
        print(f"{'PASS' if check.passed else 'FAIL'}  {check.name}: {check.detail}")
    failed = sum(not c.passed for c in checks)
    print(f"{len(checks) - failed} of {len(checks)} checks passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
