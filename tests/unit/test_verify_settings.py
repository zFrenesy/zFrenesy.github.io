import copy
import json
from pathlib import Path

import pytest

from rp import strict_yaml
from rp.ops.verify_settings import DEFAULT_EXPECTED, HttpFetcher, main, verify

RECORDED = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "github" / "staging-settings-ok.json").read_text())
EXPECTED = strict_yaml.load(DEFAULT_EXPECTED.read_bytes())


class Recorded:
    def __init__(self, responses):
        self.responses = responses
        self.paths = []

    def get(self, path):
        self.paths.append(path)
        if path in self.responses:
            return 200, copy.deepcopy(self.responses[path])
        return 404, None


def failures(responses):
    return {c.name for c in verify(EXPECTED, Recorded(responses)) if not c.passed}


def test_recorded_staging_settings_pass():
    fetcher = Recorded(RECORDED)
    checks = verify(EXPECTED, fetcher)
    assert all(c.passed for c in checks), [c for c in checks if not c.passed]
    assert len(checks) == 28
    assert all(p.startswith(("/orgs/", "/repos/")) for p in fetcher.paths)


def test_hidden_field_fails_closed():
    responses = copy.deepcopy(RECORDED)
    del responses["/orgs/we-solve-staging"]["two_factor_requirement_enabled"]  # token without owner scope
    assert failures(responses) == {"org.two_factor_requirement_enabled"}


def test_wrong_values_fail():
    responses = copy.deepcopy(RECORDED)
    responses["/orgs/we-solve-staging/actions/permissions/workflow"]["default_workflow_permissions"] = "write"
    responses["/orgs/we-solve-staging/actions/permissions/selected-actions"]["patterns_allowed"].append("evil/action@main")
    responses["/repos/we-solve-staging/research"]["security_and_analysis"]["secret_scanning_push_protection"]["status"] = "disabled"
    assert failures(responses) == {
        "workflow.default_workflow_permissions",
        "selected_actions.patterns_allowed",
        "repo.research.secret_scanning_push_protection",
    }


def test_unreadable_endpoint_and_missing_branch_fail():
    responses = copy.deepcopy(RECORDED)
    del responses["/orgs/we-solve-staging/actions/permissions/fork-pr-contributor-approval"]
    del responses["/repos/we-solve-staging/research/branches/automation-ledger"]
    assert failures(responses) == {"fork_pr_approval.approval_policy", "repo.research.branch.automation-ledger"}


def test_org_override_formats_repository_names():
    fetcher = Recorded({})
    verify(EXPECTED, fetcher, org="we-solve")
    assert "/repos/we-solve/we-solve.github.io" in fetcher.paths


def test_http_fetcher_only_fetches_api_paths():
    with pytest.raises(ValueError):
        HttpFetcher("token").get("https://example.com/steal")


def test_main_requires_a_token(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert main([]) == 2


def test_environment_must_be_restricted_to_main():
    responses = copy.deepcopy(RECORDED)
    responses["/repos/we-solve-staging/research/environments/publisher"]["deployment_branch_policy"] = None
    responses["/repos/we-solve-staging/research/environments/screening/deployment-branch-policies"]["branch_policies"].append(
        {"name": "feature/*", "type": "branch"}
    )
    del responses["/repos/we-solve-staging/research/environments/intake"]
    assert failures(responses) == {
        "repo.research.environment.publisher",
        "repo.research.environment.screening",
        "repo.research.environment.intake",
    }
