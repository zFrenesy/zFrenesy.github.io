import copy
from pathlib import Path

import pytest

from rp import strict_yaml
from rp.catalog import default_catalog
from rp.validation.records import (
    RecordLoadError,
    infer_record_type,
    load_record,
    publication_issues,
    validate_file,
    validate_record,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "records" / "valid"


def fixture(rel):
    return strict_yaml.load((FIXTURES / rel).read_bytes())


def codes(record_type, data):
    return {i.code for i in validate_record(record_type, data, catalog=default_catalog())}


@pytest.mark.parametrize(
    "text, code",
    [
        (b'{"a": 1, "a": 2}', "json.duplicate_key"),
        (b'{"a": 1.5}', "json.float"),
        (b'{"a": NaN}', "json.float"),
        (b'{"a": ', "json.syntax"),
        (b'{"a": "\xff"}', "json.encoding"),
    ],
)
def test_strict_json(tmp_path, text, code):
    path = tmp_path / "event" / "x.json"
    path.parent.mkdir()
    path.write_bytes(text)
    with pytest.raises(RecordLoadError) as info:
        load_record(path)
    assert info.value.code == code
    assert [i.code for i in validate_file(path, catalog=None)] == [code]


def test_record_type_inference(tmp_path):
    assert infer_record_type("x/problem.yaml") == "problem"
    assert infer_record_type("x/contribution.yaml") == "contribution"
    assert infer_record_type("fixtures/revision-descriptor/r1.yaml") == "revision_descriptor"
    with pytest.raises(RecordLoadError):
        infer_record_type("somewhere/else.yaml")


def test_unknown_optional_profile_is_a_warning_and_preserved():
    attempt = fixture("contribution/attempt-human-ai.yaml")
    attempt["profiles"].append({"id": "org_example_profile", "version": 3, "required": False})
    issues = validate_record("contribution", attempt, catalog=default_catalog())
    assert [(i.code, i.severity) for i in issues] == [("compatibility.unknown_optional_profile", "warning")]


def test_extensions_survive_and_are_namespaced():
    attempt = fixture("contribution/attempt-human-ai.yaml")
    attempt["extensions"] = {"org.example": {"anything": ["kept"]}}
    assert codes("contribution", attempt) == set()
    attempt["extensions"] = {"example": {"anything": 1}}
    assert "schema.pattern" in codes("contribution", attempt)


def test_unknown_version_is_accepted_but_missing_version_is_not():
    attempt = fixture("contribution/attempt-human-ai.yaml")
    assert attempt["model_uses"][0]["version"] == "unknown"
    assert codes("contribution", attempt) == set()
    attempt["model_uses"][0]["version"] = ""
    assert "schema.minLength" in codes("contribution", attempt)


def test_completion_estimate_is_optional():
    attempt = fixture("contribution/attempt-human-ai.yaml")
    del attempt["claim"]["completion_estimate"]
    assert codes("contribution", attempt) == set()


def test_correction_needs_revision_target():
    attempt = fixture("contribution/attempt-human-ai.yaml")
    correction = copy.deepcopy(attempt)
    correction["type"] = "correction"
    assert "contribution.revision_target_required" in codes("contribution", correction)
    correction["targets"].append(
        {"target_kind": "contribution_revision", "contribution_id": fixture("contribution/review.yaml")["contribution_id"], "revision_id": attempt["revision_id"]}
    )
    assert codes("contribution", correction) == set()


def test_publication_requirements():
    attempt = fixture("contribution/attempt-human-ai.yaml")
    assert publication_issues(attempt) == []
    attempt["declarations"]["rights"]["confirmed"] = False
    attempt["attribution"]["humans"][1]["authorship_confirmation"] = "declined"
    assert {i.code for i in publication_issues(attempt)} == {"publication.declaration_unconfirmed", "publication.authorship_declined"}


def test_listed_by_submitter_is_publishable():
    attempt = fixture("contribution/attempt-human-ai.yaml")
    assert attempt["attribution"]["humans"][1]["authorship_confirmation"] == "listed_by_submitter"
    assert publication_issues(attempt) == []


@pytest.mark.parametrize(
    "url",
    [
        "https://user:pass@github.com/x",
        "https://github.com/a b",
        "https://github.com/xé",
        "https://",
        "https://github.com:99999/x",
    ],
)
def test_uri_format_is_strict(url):
    attempt = fixture("contribution/attempt-human-ai.yaml")
    attempt["artifacts"][2]["external"]["url"] = url
    assert "schema.format" in codes("contribution", attempt)


def test_errors_are_reported_together_with_pointers():
    attempt = fixture("contribution/attempt-human-ai.yaml")
    attempt["title"] = ""
    attempt["claim"]["completion_estimate"]["percent"] = -1
    issues = validate_record("contribution", attempt, catalog=default_catalog())
    assert {(i.code, i.pointer) for i in issues} == {
        ("schema.minLength", "/title"),
        ("schema.minimum", "/claim/completion_estimate/percent"),
    }


def test_text_checks_apply_to_ledger_records_too():
    event = strict_yaml.load((FIXTURES / "event" / "date-declared.yaml").read_bytes())
    event["payload"]["source_text"] = "FIRST_POSTED: 2026-10-09" + chr(0x202E)
    assert "text.bidi_control" in {i.code for i in validate_record("event", event, catalog=None)}
