"""The synthetic §11 benchmark fixture is deterministic, valid, and replays to the same ledger state."""

import json
from pathlib import Path

import pytest

from rp import strict_yaml
from rp.catalog import default_catalog
from rp.identity.relations import check_relations, relations_from_problem
from rp.ledger.state import rebuild
from rp.ledger.store import MemoryLedger
from rp.validation.records import validate_record
from tests.fixtures.synthetic import generate

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "golden" / "synthetic-seed-1.json"


@pytest.fixture(scope="module")
def tree(tmp_path_factory):
    out = tmp_path_factory.mktemp("synthetic")
    return out, generate(out, "1")


def test_matches_golden_summary(tree):
    _, summary = tree
    assert summary == json.loads(GOLDEN.read_text())


def test_same_seed_is_byte_identical_and_other_seeds_differ(tree):
    _, summary = tree
    assert generate(None, "1") == summary
    assert generate(None, "2", attempts=40, contributors=10, subproblems=3, reviews=5)["tree_digest"] != summary["tree_digest"]


def test_benchmark_shape(tree):
    _, summary = tree
    attempt_like = sum(n for t, n in summary["contributions"].items() if t != "review")
    assert attempt_like == 500
    assert summary["problems"]["derived"] == 30
    assert summary["contributors"] >= 200


def records(out: Path, name: str):
    for path in sorted((out / "research" / "problems").rglob(name)):
        yield path, strict_yaml.load(path.read_bytes())


def test_every_record_is_valid(tree):
    out, _ = tree
    catalog = default_catalog()
    problems = dict(records(out, "problem.yaml"))
    contributions = dict(records(out, "contribution.yaml"))
    assert len(problems) == 105 and len(contributions) == 560
    for path, data in [*problems.items(), *contributions.items()]:
        errors = [i for i in validate_record(path.name.removesuffix(".yaml"), data, catalog=catalog) if i.severity == "error"]
        assert errors == [], (path, errors)
    relations = [r for p in problems.values() for r in relations_from_problem(p)]
    assert check_relations(relations, {p["problem_id"] for p in problems.values()}) == []


def test_ledger_replays_to_the_same_state(tree):
    out, summary = tree
    lines = (out / "ledger" / "events.jsonl").read_bytes().splitlines()
    events = [json.loads(line) for line in lines]
    replayed = MemoryLedger.from_events(events)
    assert replayed.read()[0] == summary["ledger_head"]
    state = rebuild(events)
    assert len(state.aliases) == summary["aliases"]
    assert all(rec.state == "bound" for rec in state.aliases.values())
    assert len({rec.entity_id for rec in state.aliases.values()}) == len(state.aliases)
    assert state.active_snapshot is not None
    for event in events:
        assert validate_record("event", event, catalog=None) == []


def test_legacy_shaped_cases_are_present(tree):
    out, _ = tree
    contributions = [data for _, data in records(out, "contribution.yaml")]
    legacy = [c for c in contributions if c["type"] == "legacy_record"]
    assert any(c["lineage"] and c["lineage"][0]["lineage_status"] == "unknown" for c in legacy)
    assert all(use["version"] == "unknown" for c in legacy for use in c["model_uses"])
    human_folder = [c for c in legacy if "org.we-solve.legacy" in c.get("extensions", {})]
    assert len(human_folder) == 1 and human_folder[0]["attribution"]["contribution_mode"] == "human_ai"
    events = [json.loads(line) for line in (out / "ledger" / "events.jsonl").read_bytes().splitlines()]
    first_posted = [e for e in events if e["type"] == "date_declared"]
    assert len(first_posted) == len(legacy)
    assert all(e["occurred_at"]["precision"] == "day" and e["time_source"] == "legacy_header" for e in first_posted)
    # Declared dates never become publication or merge times.
    merged = {e["payload"]["contribution_id"] for e in events if e["type"] == "revision_merged"}
    assert all(e["occurred_at"]["value"] != e["recorded_at"] for e in first_posted)
    assert {c["contribution_id"] for c in legacy} <= merged
