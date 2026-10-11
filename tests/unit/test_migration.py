import hashlib
import json
import os
from pathlib import Path

import pytest

from rp import strict_yaml
from rp.catalog import default_catalog
from rp.identity.ids import SeededIdSource
from rp.ledger.state import rebuild
from rp.ledger.store import MemoryLedger
from rp.migration.headers import parse_headers
from rp.migration.importer import IMPORT_ID, LegacyImporter
from rp.migration.inventory import build_inventory
from rp.migration.legacy_git import LegacyRepo
from rp.migration.reviews import review_history
from rp.timeutil import FixedClock
from rp.validation.records import validate_record
from tests.fixtures.legacy_repo import SNAPSHOT, build_legacy_repo


@pytest.fixture(scope="module")
def legacy(tmp_path_factory):
    path, commit = build_legacy_repo(tmp_path_factory.mktemp("legacy"))
    return LegacyRepo(path, commit)


def run_import(legacy, out, seed="m"):
    return LegacyImporter(legacy, out, id_source=SeededIdSource(seed), clock=FixedClock("2026-10-11T00:00:00Z"), snapshot=SNAPSHOT).run()


@pytest.fixture(scope="module")
def imported(legacy, tmp_path_factory):
    out = tmp_path_factory.mktemp("out")
    return out, run_import(legacy, out)


def tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        h.update(str(path.relative_to(root)).encode() + b"\0" + path.read_bytes())
    return h.hexdigest()


def test_headers_are_data_only():
    h = parse_headers('% FIRST_POSTED: 2026-10-09\n% ATTEMPT_STATUS: Partial\n% TOP_PROBLEM: {"id": 1}\n% MODEL: X\n')
    assert (h.first_posted, h.attempt_status, h.data["TOP_PROBLEM"]) == ("2026-10-09", "partial", {"id": 1})
    bad = parse_headers("% FIRST_POSTED: 2026-13-01\n% ATTEMPT_STATUS: solved\n% ATTEMPT_STATUS: unresolved\n% OPENAI_CLAIM: {oops\n")
    assert bad.first_posted is None and bad.attempt_status is None
    assert {i.split(" ")[0] for i in bad.issues} >= {"OPENAI_CLAIM", "FIRST_POSTED", "conflicting"}


def test_inventory_classifies_every_file(legacy):
    inv = build_inventory(legacy)
    classes = {e.path: e.cls for e in inv.entries}
    assert classes["attacks/open_problems/erdos/gpt_pro_5.2/5.tex"] == "attempt"
    assert classes["attacks/open_problems/erdos/GPT_6_Astra_Ultra/1.tex"] == "reused_writeup"
    assert classes["attacks/open_problems/top_problems/gpt_6_astra_pro/30006001.tex"] == "statement_copy"
    assert classes["attacks/open_problems/top_problems/openai/10.tex"] == "external_claim_summary"
    assert classes["attacks/open_problems/top_problems/Human_Contribution/30007097.tex"] == "human_contribution"
    assert classes["attacks/open_problems/erdos/gpt_pro_5.4/IMPORTS.md"] == "import_note"
    assert classes["attacks/open_problems/top_problems/definitions/10.tex"] == "statement"
    assert classes["README.md"] == "non_research"
    assert classes["lists/erdos_status.json"] == "catalogue_list"
    assert "unclassified" not in classes.values()
    odd = next(e for e in inv.entries if e.path.endswith("3_2.tex"))
    assert odd.problem_key == "erdos:3" and odd.uncertainty


def test_review_history_includes_edits_and_deletion(legacy):
    histories = review_history(legacy)
    five = histories["reviews/erdos/5.json"]
    assert [v.data["note"] for v in five.versions] == ["Known result.", "Known result (edited)."]
    one = histories["reviews/erdos/1.json"]
    assert one.deleted and one.current.data["label"] == "incorrect"


def test_first_added_dates_follow_legacy_renames(legacy):
    added = legacy.first_added("attacks")
    assert added["attacks/erdos/gpt_pro_5.2/5.tex"] == "2026-01-16T09:00:00Z"


def records(out: Path, name: str):
    return {p: strict_yaml.load(p.read_bytes()) for p in (out / "research" / "problems").rglob(name)}


def test_import_counts_and_validity(imported):
    out, result = imported
    assert result.counts == {
        "contributions_attempt": 7,
        "contributions_external_claim_summary": 1,
        "contributions_human_contribution": 1,
        "contributions_review": 2,
        "contributions_reused_writeup": 1,
        "contributions_statement_copy": 1,
        "problems_economics": 1,
        "problems_erdos": 3,
        "problems_mo": 1,
        "problems_top": 3,
    }
    catalog = default_catalog()
    for kind, name in (("problem", "problem.yaml"), ("contribution", "contribution.yaml")):
        for path, record in records(out, name).items():
            errors = [i for i in validate_record(kind, record, catalog=catalog) if i.severity == "error"]
            assert errors == [], (path, errors)


def test_reimport_is_byte_identical(legacy, imported):
    out, first = imported
    before = tree_digest(out)
    second = run_import(legacy, out, seed="different-seed")  # the mapping, not the seed, decides IDs
    assert tree_digest(out) == before
    assert (second.events, second.ledger_head) == (first.events, first.ledger_head)


def test_changed_content_is_refused_on_reimport(legacy, tmp_path):
    run_import(legacy, tmp_path)
    mapping = tmp_path / "research" / "migration" / IMPORT_ID / "mapping.jsonl"
    lines = [json.loads(line) for line in mapping.read_text().splitlines()]
    for line in lines:
        if line.get("scientific_fingerprint"):
            line["scientific_fingerprint"] = "sha256:" + "0" * 64
            break
    mapping.write_text("".join(json.dumps(line) + "\n" for line in lines))
    with pytest.raises(RuntimeError, match="needs a new revision"):
        run_import(legacy, tmp_path)


def test_ledger_replays_and_aliases_are_bound(imported):
    out, result = imported
    events = [json.loads(line) for line in (out / "ledger" / "events.jsonl").read_text().splitlines()]
    assert MemoryLedger.from_events(events).head() == result.ledger_head
    state = rebuild(events)
    aliases = set(state.aliases)
    assert {"ERDOS-1", "ERDOS-3", "ERDOS-5", "ECON-C73-1", "TOP-10", "TOP-30007097", "TOP-30006001", "MO-339137"} <= aliases
    assert all(r.state == "bound" for r in state.aliases.values())
    assert len(state.revision_labels) == 13 and set(state.revision_labels.values()) == {"r1"}


def by_source(out: Path) -> dict[str, dict]:
    found = {}
    for record in records(out, "contribution.yaml").values():
        ext = record["extensions"]["org.we-solve.legacy"]
        found[ext["source_path"]] = record
    return found


def test_legacy_semantics(imported):
    out, _ = imported
    c = by_source(out)
    base = "attacks/open_problems/"
    v1, v2 = c[base + "economics/gpt_6_astra_pro/C73-1.tex"], c[base + "economics/gpt_6_astra_pro/C73-1_v2.tex"]
    assert v2["lineage"] == [{"relation": "derivative_of", "contribution_id": v1["contribution_id"], "revision_id": v1["revision_id"],
                              "lineage_status": "known", "note": "REVISION_OF: gpt_6_astra_pro/C73-1.tex"}]
    erdos_v2 = c[base + "erdos/gpt_pro_5.2/5_v2.tex"]
    assert erdos_v2["lineage"][0]["relation"] == "possible_revision_of" and erdos_v2["lineage"][0]["lineage_status"] == "unknown"
    assert erdos_v2["claim"]["type"] == "partial_result"
    reused = c[base + "erdos/GPT_6_Astra_Ultra/1.tex"]
    assert reused["lineage"][0]["relation"] == "reuses"
    assert reused["model_uses"][0]["declared_name"] == "gpt pro 5.2"  # the source model, not the collection folder
    erdos_v1 = c[base + "erdos/gpt_pro_5.2/5.tex"]
    assert "claim" not in erdos_v1  # no declared status: the legacy inferred value is retired, not a claim
    assert "retired_inferred_status" in erdos_v1["extensions"]["org.we-solve.legacy"]
    top = c[base + "top_problems/gpt_6_astra_ultra/10.tex"]
    assert top["claim"]["type"] == "full_solution" and top["model_uses"][0]["provenance"]["level"] == "declared"
    openai = c[base + "top_problems/openai/10.tex"]
    assert openai["claim"]["type"] == "literature_report"
    assert openai["artifacts"][1]["external"]["pin"] == {"kind": "git_commit", "value": "b" * 40}
    human = c[base + "top_problems/Human_Contribution/30007097.tex"]
    assert human["attribution"]["contribution_mode"] == "human_ai"
    assert human["attribution"]["humans"][0]["authorship_confirmation"] == "listed_by_submitter"
    assert human["rights"]["licence"] == "CC-BY-4.0"
    copy = c[base + "top_problems/gpt_6_astra_pro/30006001.tex"]
    assert "claim" not in copy and copy["extensions"]["org.we-solve.legacy"]["uncertainty"]


def test_problems_rights_and_sources(imported):
    out, _ = imported
    problems = {r["extensions"]["org.we-solve.legacy"]["collection"] + ":" + r["external_ids"][0]["identifier"]: r for r in records(out, "problem.yaml").values()}
    assert problems["top:10"]["rights"]["licence"] == "CC-BY-SA-4.0"  # OWR- source keeps ShareAlike
    assert problems["top:30006001"]["disciplines"][0]["discipline"] == "computer-science"
    assert [x["scheme"] for x in problems["top:30006001"]["external_ids"]] == ["legacy-top-open-problems"]  # LOCAL: no UnsolvedMath ID
    assert problems["erdos:1"]["sources"][0]["normalised_status"] == "proved"
    assert problems["erdos:1"]["statement_artifact"]["path"] == "statement.md"
    assert problems["erdos:3"]["sources"] == []
    assert problems["mo:339137"]["title"] == "Synthetic MO & question"
    assert problems["economics:C73-1"]["classifications"] == [{"scheme": "jel", "code": "C73"}]


def test_dates_never_become_publication_dates(imported):
    out, _ = imported
    events = [json.loads(line) for line in (out / "ledger" / "events.jsonl").read_text().splitlines()]
    declared = [e for e in events if e["type"] == "date_declared"]
    kinds = {(e["payload"]["kind"], e["time_source"], e["occurred_at"]["precision"]) for e in declared}
    assert ("first_posted", "legacy_header", "day") in kinds
    assert ("repository_first_added", "git_author_date", "instant") in kinds
    assert not any(e["type"] == "snapshot_activated" for e in events)


def test_review_record_keeps_history_and_roles(imported):
    out, _ = imported
    c = by_source(out)
    review = c["reviews/erdos/5.json"]
    ext = review["extensions"]["org.we-solve.legacy"]
    assert ext["issues"]["26"] == {"url": "https://github.com/mehmetmars7/Erdosproblems-llm-hunter/issues/26", "author": "reviewer-a", "labellers": ["mehmetmars7"]}
    files = next(p.parent for p, r in records(out, "contribution.yaml").items() if r["contribution_id"] == review["contribution_id"])
    history = json.loads((files / "files" / "review-history.json").read_text())
    assert len(history["versions"]) == 2
    deleted = c["reviews/erdos/1.json"]
    assert deleted["extensions"]["org.we-solve.legacy"]["deleted"] is True


def test_mapping_records_sources(imported):
    out, _ = imported
    lines = [json.loads(line) for line in (out / "research" / "migration" / IMPORT_ID / "mapping.jsonl").read_text().splitlines()]
    keys = {line["key"] for line in lines}
    assert "contribution:attacks/open_problems/mo/gpt_pro_5.2/339137 - Synthetic question.tex" in keys
    mo = next(line for line in lines if line["key"].startswith("contribution:attacks/open_problems/mo/"))
    assert mo["files"] == {"files/339137-Synthetic-question.tex": "339137 - Synthetic question.tex"}
    assert mo["source"]["repository_id"] == 1136156171


@pytest.mark.skipif(not os.environ.get("RP_LEGACY_CLONE"), reason="set RP_LEGACY_CLONE to the legacy clone to run the full import")
def test_full_legacy_import(tmp_path):  # pragma: no cover - slow, opt-in
    repo = LegacyRepo(os.environ["RP_LEGACY_CLONE"])
    result = LegacyImporter(repo, tmp_path).run()
    inv = json.loads((tmp_path / "research" / "migration" / IMPORT_ID / "inventory.json").read_text())
    assert inv["attacks_files"] == 9965
    assert sum(v for k, v in result.counts.items() if k.startswith("contributions_")) == 5154
