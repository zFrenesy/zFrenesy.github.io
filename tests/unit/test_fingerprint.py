import copy
import os
from pathlib import Path

import pytest

from rp import strict_yaml
from rp.fingerprint import (
    BindingError,
    ManifestError,
    authorization_binding,
    editor_state_digest,
    manifest_from_blobs,
    manifest_from_directory,
    problem_fingerprint,
    scientific_fingerprint,
)
from rp.identity.ids import SeededIdSource, new_id

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "records" / "valid"
IDS = SeededIdSource("fingerprint-tests")
BLOBS = {
    "files/attempt.tex": (b"\\section{Proof}\nLet k = 3.\n", "100644"),
    "files/refs.bib": (b"@article{x,title={Y}}\n", "100644"),
}


@pytest.fixture
def attempt():
    return strict_yaml.load((FIXTURES / "contribution" / "attempt-human-ai.yaml").read_bytes())


def fingerprint(contribution, blobs=BLOBS):
    return scientific_fingerprint(contribution, manifest_from_blobs(blobs, contribution["artifacts"]))


def test_manifest_is_sorted_and_hashes_exact_bytes(attempt):
    manifest = manifest_from_blobs(dict(reversed(list(BLOBS.items()))), attempt["artifacts"])
    assert [e.get("logical_path", e.get("url")) for e in manifest] == [
        "files/attempt.tex",
        "files/refs.bib",
        "https://github.com/example/search-code",
    ]
    assert manifest[0]["bytes"] == len(BLOBS["files/attempt.tex"][0])
    assert manifest[0]["digest"].startswith("sha256:")


@pytest.mark.parametrize(
    "blobs, code",
    [
        ({"files/attempt.tex": BLOBS["files/attempt.tex"]}, "manifest.missing_file"),
        ({**BLOBS, "files/extra.tex": (b"x", "100644")}, "manifest.undeclared_file"),
        ({**BLOBS, "files/link": (b"/etc/passwd", "120000")}, "manifest.mode"),
        ({**BLOBS, "files/sub": (b"", "160000")}, "manifest.mode"),
        ({**BLOBS, "contribution.yaml.bak": (b"x", "100644")}, "manifest.outside_files"),
        ({**BLOBS, "files/../../x": (b"x", "100644")}, "manifest.path"),
    ],
)
def test_manifest_rejections(attempt, blobs, code):
    with pytest.raises(ManifestError) as info:
        manifest_from_blobs(blobs, attempt["artifacts"])
    assert info.value.code == code


def test_duplicate_external_link_is_rejected(attempt):
    attempt["artifacts"].append(copy.deepcopy(attempt["artifacts"][2]))
    with pytest.raises(ManifestError) as info:
        manifest_from_blobs(BLOBS, attempt["artifacts"])
    assert info.value.code == "manifest.duplicate"


def test_manifest_from_directory(tmp_path, attempt):
    (tmp_path / "files").mkdir()
    for rel, (content, _) in BLOBS.items():
        (tmp_path / rel).write_bytes(content)
    assert manifest_from_directory(tmp_path, attempt["artifacts"]) == manifest_from_blobs(BLOBS, attempt["artifacts"])
    os.chmod(tmp_path / "files" / "refs.bib", 0o755)
    modes = {e["logical_path"]: e["mode"] for e in manifest_from_directory(tmp_path, attempt["artifacts"]) if "logical_path" in e}
    assert modes["files/refs.bib"] == "100755"


def test_manifest_from_directory_rejects_symlinks(tmp_path, attempt):
    (tmp_path / "files").mkdir()
    for rel, (content, _) in BLOBS.items():
        (tmp_path / rel).write_bytes(content)
    (tmp_path / "files" / "escape").symlink_to("/etc")
    with pytest.raises(ManifestError) as info:
        manifest_from_directory(tmp_path, attempt["artifacts"])
    assert info.value.code == "manifest.symlink"


def test_identity_only_changes_keep_s(attempt):
    original = fingerprint(attempt)
    renamed = copy.deepcopy(attempt)
    renamed["contribution_id"] = new_id("contribution", IDS)
    renamed["revision_id"] = new_id("revision", IDS)
    renamed["expected_predecessor"] = new_id("revision", IDS)
    renamed["artifacts"][0]["artifact_id"] = new_id("artifact", IDS)
    renamed["targets"].reverse()
    assert fingerprint(renamed) == original


def mutate(path, value):
    def apply(record):
        target = record
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
    return apply


@pytest.mark.parametrize(
    "change",
    [
        mutate(["title"], "Another title"),
        mutate(["claim", "type"], "full_solution"),
        mutate(["claim", "scope_statement"], "Proves k = 3 and k = 4."),
        mutate(["model_uses", 0, "version"], "example-model-2026-10-01"),
        mutate(["rights", "licence"], "CC-BY-SA-4.0"),
        mutate(["targets", 0, "statement_revision_id"], new_id("statement_revision", IDS)),
        mutate(["artifacts", 2, "external", "pin", "value"], "c" * 40),
        mutate(["artifacts", 0, "role"], "manuscript"),
        lambda r: r["attribution"]["humans"].reverse(),
        lambda r: r["lineage"].append(
            {"relation": "extends", "contribution_id": new_id("contribution", IDS), "revision_id": None, "lineage_status": "known"}
        ),
    ],
)
def test_scientific_changes_change_s(attempt, change):
    changed = copy.deepcopy(attempt)
    change(changed)
    assert fingerprint(changed) != fingerprint(attempt)


def test_one_source_byte_changes_s(attempt):
    content, mode = BLOBS["files/attempt.tex"]
    altered = {**BLOBS, "files/attempt.tex": (content[:-2] + b"4\n", mode)}
    assert fingerprint(attempt, altered) != fingerprint(attempt)


BINDING = dict(
    repository="we-solve/research",
    pull_request=42,
    head_sha="a" * 40,
    base_sha="b" * 40,
    scientific_fingerprint="sha256:" + "1" * 64,
    expected_predecessor=None,
    policy_version="policy/1",
    rubric_version="rubric/1",
    review_context_digest="sha256:" + "2" * 64,
    editor_state_digest="sha256:" + "3" * 64,
)


@pytest.mark.parametrize(
    "field, value",
    [
        ("repository", "we-solve/research-fork"),
        ("pull_request", 43),
        ("head_sha", "c" * 40),
        ("base_sha", "d" * 40),
        ("scientific_fingerprint", "sha256:" + "4" * 64),
        ("expected_predecessor", "rev_" + "0" * 12 + "4" + "0" * 3 + "8" + "0" * 15),
        ("policy_version", "policy/2"),
        ("rubric_version", "rubric/2"),
        ("review_context_digest", "sha256:" + "5" * 64),
        ("editor_state_digest", "sha256:" + "6" * 64),
    ],
)
def test_every_binding_input_changes_k(field, value):
    assert authorization_binding(**{**BINDING, field: value}) != authorization_binding(**BINDING)


@pytest.mark.parametrize(
    "field, value",
    [
        ("repository", ""),
        ("pull_request", 0),
        ("pull_request", True),
        ("head_sha", "main"),
        ("base_sha", None),
        ("scientific_fingerprint", "1" * 64),
        ("expected_predecessor", "con_" + "0" * 12 + "4" + "0" * 3 + "8" + "0" * 15),
        ("policy_version", "1"),
        ("rubric_version", None),
        ("review_context_digest", ""),
        ("editor_state_digest", None),
    ],
)
def test_binding_fails_closed_on_bad_inputs(field, value):
    with pytest.raises(BindingError):
        authorization_binding(**{**BINDING, field: value})


def test_stale_authorization_detection_end_to_end(attempt):
    """Acceptance §12: changing metadata, statement, bytes, pins or context invalidates K."""

    def k(contribution, blobs=BLOBS, context="sha256:" + "2" * 64):
        return authorization_binding(**{**BINDING, "scientific_fingerprint": fingerprint(contribution, blobs), "review_context_digest": context})

    authorised = k(attempt)
    variants = []
    meta = copy.deepcopy(attempt)
    meta["claim"]["limitations"] = []
    variants.append(k(meta))
    statement = copy.deepcopy(attempt)
    statement["targets"][0]["statement_revision_id"] = new_id("statement_revision", IDS)
    variants.append(k(statement))
    content, mode = BLOBS["files/refs.bib"]
    variants.append(k(attempt, {**BLOBS, "files/refs.bib": (content + b" ", mode)}))
    pin = copy.deepcopy(attempt)
    pin["artifacts"][2]["external"]["pin"]["value"] = "e" * 40
    variants.append(k(pin))
    variants.append(k(attempt, context="sha256:" + "9" * 64))
    assert authorised not in variants
    assert len(set(variants)) == len(variants)


def test_editor_state_digest():
    owner, a, b = (new_id("person", IDS) for _ in range(3))
    assert editor_state_digest(owner=owner, editors=[a, b]) == editor_state_digest(owner=owner, editors=[b, a, a])
    assert editor_state_digest(owner=owner, editors=[a]) != editor_state_digest(owner=a, editors=[owner])
    with pytest.raises(BindingError):
        editor_state_digest(owner="mehmet", editors=[])


def test_problem_fingerprint():
    problem = strict_yaml.load((FIXTURES / "problem" / "proposed.yaml").read_bytes())
    base = problem_fingerprint(problem, b"Statement.")
    renamed = dict(problem, problem_id=new_id("problem", IDS), statement_revision_id=new_id("statement_revision", IDS))
    assert problem_fingerprint(renamed, b"Statement.") == base
    assert problem_fingerprint(problem, b"Statement!") != base
    assert problem_fingerprint(dict(problem, title="Other"), b"Statement.") != base
