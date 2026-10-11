"""Publication reads only exact accepted revisions and their validated ledger."""

import json
import shutil

import pytest

from rp import strict_yaml
from rp.site.model import load_model
from tests.fixtures.synthetic import generate


@pytest.fixture(scope="module")
def accepted_tree(tmp_path_factory):
    work = tmp_path_factory.mktemp("accepted-site-model")
    summary = generate(work, "site-model", attempts=40, contributors=5, subproblems=2, reviews=3)
    return work, summary


@pytest.fixture
def work(accepted_tree, tmp_path):
    result = tmp_path / "work"
    shutil.copytree(accepted_tree[0], result)
    return result


def record(work, kind="contribution"):
    path = next((work / "research").rglob(kind + ".yaml"))
    return path, strict_yaml.load(path.read_bytes())


def events(work):
    return [json.loads(line) for line in (work / "ledger/events.jsonl").read_text().splitlines()]


def write_events(work, values):
    (work / "ledger/events.jsonl").write_text("".join(json.dumps(value) + "\n" for value in values))


def test_valid_synthetic_revisions_have_matching_real_fingerprints(accepted_tree):
    model = load_model(accepted_tree[0])
    summary = accepted_tree[1]
    assert len(model.problems) == sum(summary["problems"].values())
    assert len(model.contributions) == sum(summary["contributions"].values())
    assert all(c.accepted_at and c.alias for c in model.contributions.values())
    assert any(c.revision_label == "r2" for c in model.contributions.values())


def test_modified_artifact_cannot_be_published_under_accepted_revision(work):
    path, data = record(work)
    artifact = next(a["path"] for a in data["artifacts"] if a["location"] == "in_repository")
    source = path.parent / artifact
    source.write_bytes(source.read_bytes() + b"A changed conclusion.\n")
    with pytest.raises(ValueError, match="accepted scientific fingerprint"):
        load_model(work)


def test_modified_authored_metadata_cannot_reuse_accepted_revision(work):
    path, data = record(work)
    data["title"] = "Changed claim"
    path.write_text(strict_yaml.dump(data))
    with pytest.raises(ValueError, match="accepted scientific fingerprint"):
        load_model(work)


def test_filesystem_mode_is_part_of_accepted_artifact_manifest(work):
    path, data = record(work)
    artifact = next(a["path"] for a in data["artifacts"] if a["location"] == "in_repository")
    (path.parent / artifact).chmod(0o755)
    with pytest.raises(ValueError, match="accepted scientific fingerprint"):
        load_model(work)


@pytest.mark.parametrize("change", ["missing", "undeclared", "directory_symlink"])
def test_artifact_set_must_match_the_accepted_manifest(work, change):
    path, data = record(work)
    artifact = next(a["path"] for a in data["artifacts"] if a["location"] == "in_repository")
    if change == "missing":
        (path.parent / artifact).unlink()
        message = "manifest.missing_file"
    elif change == "undeclared":
        (path.parent / "files/addition.txt").write_text("Unaccepted attachment")
        message = "manifest.undeclared_file"
    else:
        (path.parent / "files/extra").symlink_to(path.parent, target_is_directory=True)
        message = "symlink artifact"
    with pytest.raises(ValueError, match=message):
        load_model(work)


def test_revision_must_belong_to_the_same_contribution(work):
    path, data = record(work)
    other = next(e["payload"] for e in events(work) if e["type"] == "revision_accepted"
                 and e["payload"]["contribution_id"] != data["contribution_id"])
    data["revision_id"] = other["revision_id"]
    path.write_text(strict_yaml.dump(data))
    with pytest.raises(ValueError, match="does not match its accepted revision"):
        load_model(work)


def test_predecessor_cannot_be_rewritten_even_though_it_is_not_part_of_s(work):
    model = load_model(work)
    contribution = next(c for c in model.contributions.values() if c.revision_label == "r2")
    data = dict(contribution.record, expected_predecessor=None)
    (contribution.folder / "contribution.yaml").write_text(strict_yaml.dump(data))
    with pytest.raises(ValueError, match="does not match its accepted revision"):
        load_model(work)


def test_reserved_alias_is_not_publishable(work):
    _, data = record(work)
    log = events(work)
    write_events(work, [e for e in log if not (e["type"] == "alias_bound" and e["payload"]["entity_id"] == data["contribution_id"])])
    with pytest.raises(ValueError, match="no bound alias"):
        load_model(work)


def test_statement_bytes_are_checked_against_accepted_descriptor(work):
    path, data = record(work, "problem")
    source = path.parent / data["statement_artifact"]["path"]
    source.write_bytes(source.read_bytes() + b"Another hypothesis.\n")
    with pytest.raises(ValueError, match="statement source differs from its accepted descriptor"):
        load_model(work)


@pytest.mark.parametrize("change", ["missing", "wrong_problem", "wrong_digest", "wrong_date"])
def test_statement_descriptor_is_required_and_bound_to_record(work, change):
    _, data = record(work, "problem")
    path = work / "ledger/statement-revisions" / (data["statement_revision_id"] + ".json")
    descriptor = json.loads(path.read_text())
    if change == "missing":
        path.unlink()
        message = "missing publication source"
    else:
        if change == "wrong_problem":
            descriptor["problem_id"] = next(e["payload"]["problem_id"] for e in events(work)
                                            if e["type"] == "statement_revised" and e["payload"]["problem_id"] != data["problem_id"])
        elif change == "wrong_digest":
            descriptor["statement_artifact"]["digest"] = "sha256:" + "0" * 64
        else:
            descriptor["recorded_at"] = "2020-01-01T00:00:00Z"
        path.write_text(json.dumps(descriptor))
        message = "accepted descriptor"
    with pytest.raises(ValueError, match=message):
        load_model(work)


def test_statement_revision_must_belong_to_the_problem(work):
    path, data = record(work, "problem")
    data["statement_revision_id"] = next(e["payload"]["statement_revision_id"] for e in events(work)
                                          if e["type"] == "statement_revised" and e["payload"]["problem_id"] != data["problem_id"])
    path.write_text(strict_yaml.dump(data))
    with pytest.raises(ValueError, match="accepted statement revision"):
        load_model(work)


@pytest.mark.parametrize("field", ["event_id", "idempotency_key"])
def test_duplicate_ledger_identifiers_are_rejected(work, field):
    log = events(work)
    log[1][field] = log[0][field]
    write_events(work, log)
    with pytest.raises(ValueError, match="duplicate event ID or idempotency key"):
        load_model(work)


def test_malformed_ledger_event_is_not_silently_ignored(work):
    log = events(work)
    log.append({"type": "unknown_custom_event", "payload": {}})
    write_events(work, log)
    with pytest.raises(ValueError, match="invalid event input"):
        load_model(work)


def test_duplicate_json_keys_in_ledger_are_rejected(work):
    (work / "ledger/events.jsonl").write_text('{"schema_version":1,"schema_version":2}\n')
    with pytest.raises(ValueError, match="duplicate JSON field"):
        load_model(work)


def test_duplicate_records_cannot_silently_overwrite_an_entity(work):
    path, _ = record(work, "problem")
    destination = work / "research/problems/zz" / path.parent.name
    shutil.copytree(path.parent, destination)
    with pytest.raises(ValueError, match="duplicate problem record|source path does not match"):
        load_model(work)


def test_missing_accepted_current_record_is_an_error(work):
    path, _ = record(work)
    shutil.rmtree(path.parent)
    with pytest.raises(ValueError, match="accepted contribution source is missing"):
        load_model(work)


def test_record_cannot_move_to_a_different_home_problem(work):
    path, data = record(work)
    other = next(e["payload"] for e in events(work)
                 if e["type"] == "statement_revised" and e["payload"]["problem_id"] != data["home_problem_id"])
    data["home_problem_id"] = other["problem_id"]
    data["targets"] = [{"target_kind": "problem", "problem_id": other["problem_id"],
                        "statement_revision_id": other["statement_revision_id"], "scope": "whole_statement"}]
    path.write_text(strict_yaml.dump(data))
    with pytest.raises(ValueError, match="source path does not match its home problem"):
        load_model(work)
