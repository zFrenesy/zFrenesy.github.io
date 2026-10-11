import re
import uuid

import pytest

from rp.identity.ids import (
    KIND_PREFIXES,
    InvalidIdentifier,
    SeededIdSource,
    id_kind,
    id_pattern,
    is_id,
    new_id,
    parse_id,
)
from rp.identity.paths import (
    InvalidPath,
    check_relative_path,
    contribution_dir,
    parse_research_path,
    problem_dir,
    problem_shard,
)


@pytest.mark.parametrize("kind", sorted(KIND_PREFIXES))
def test_new_ids_are_prefixed_uuid4(kind):
    value = new_id(kind)
    parsed = parse_id(value, kind)
    assert value.startswith(KIND_PREFIXES[kind] + "_")
    assert parsed.uuid.version == 4
    assert parsed.uuid.variant == uuid.RFC_4122
    assert re.fullmatch(id_pattern(kind), value)
    assert id_kind(value) == kind


def test_seeded_source_is_deterministic_and_distinct():
    a = [new_id("problem", SeededIdSource("s")) for _ in range(1)]
    src1, src2 = SeededIdSource("seed"), SeededIdSource("seed")
    first = [new_id("problem", src1) for _ in range(100)]
    second = [new_id("problem", src2) for _ in range(100)]
    assert first == second
    assert len(set(first)) == 100
    assert a[0] != first[0]


@pytest.mark.parametrize(
    "value",
    [
        "prb_" + "0" * 32,  # version nibble is not 4
        "prb_3f2a9c0e8b7d4e1f06c5b4d3e2f1a0b9",  # variant nibble 0
        "PRB_3f2a9c0e8b7d4e1fa6c5b4d3e2f1a0b9",
        "prb_3F2A9C0E8B7D4E1FA6C5B4D3E2F1A0B9",
        "prb-3f2a9c0e8b7d4e1fa6c5b4d3e2f1a0b9",
        "xyz_3f2a9c0e8b7d4e1fa6c5b4d3e2f1a0b9",
        "prb_3f2a9c0e-8b7d-4e1f-a6c5-b4d3e2f1a0b9",
        "prb_3f2a9c0e8b7d4e1fa6c5b4d3e2f1a0b9 ",
        None,
        42,
    ],
)
def test_invalid_ids(value):
    assert not is_id(value)


def test_kind_mismatch():
    with pytest.raises(InvalidIdentifier):
        parse_id(new_id("contribution"), "problem")


def test_problem_paths_are_sharded_by_uuid():
    pid = new_id("problem", SeededIdSource("paths"))
    cid = new_id("contribution", SeededIdSource("paths-c"))
    assert problem_dir(pid).parts == ("problems", pid[4:6], pid)
    assert problem_shard(pid) == pid[4:6]
    assert contribution_dir(pid, cid, "attempt").parts[-2:] == ("contributions", cid)
    assert contribution_dir(pid, cid, "review").parts[-2:] == ("reviews", cid)
    assert contribution_dir(pid, cid, "author_response").parts[-2:] == ("reviews", cid)


def test_parse_research_path():
    pid = new_id("problem", SeededIdSource("p"))
    cid = new_id("contribution", SeededIdSource("c"))
    base = str(problem_dir(pid))
    assert parse_research_path(f"{base}/problem.yaml").area == "problem"
    parsed = parse_research_path(f"{base}/contributions/{cid}/files/proof.tex")
    assert (parsed.area, parsed.entity_id, parsed.rest) == ("contributions", cid, "files/proof.tex")
    with pytest.raises(InvalidPath):
        parse_research_path(f"problems/zz/{pid}/problem.yaml")  # wrong shard
    with pytest.raises(InvalidPath):
        parse_research_path(f"{base}/contributions/not-an-id/x.md")


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/etc/passwd",
        "files/../../secret",
        "files/./a.tex",
        "files//a.tex",
        "files\\a.tex",
        "files/.hidden",
        "files/a\x00.tex",
        "files/café.tex",
        "files/a b.tex",
        "-rf",
    ],
)
def test_unsafe_relative_paths(path):
    with pytest.raises(InvalidPath):
        check_relative_path(path)


def test_safe_relative_path():
    assert str(check_relative_path("files/sub/proof_v2.tex")) == "files/sub/proof_v2.tex"
