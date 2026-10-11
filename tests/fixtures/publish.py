"""Test-only publication into an imported work tree: alias, ledger acceptance and files.

The real serialised publisher arrives in milestone 5; this helper lets site tests
render records that only intake can create (reviews, subproblems).
"""

from __future__ import annotations

import json
from pathlib import Path

from rp import strict_yaml
from rp.canonical import canonical_json, digest, sha256_digest
from rp.catalog import default_catalog
from rp.fingerprint import manifest_from_blobs, scientific_fingerprint
from rp.identity.aliases import plan_contribution_alias, plan_subproblem_alias
from rp.identity.paths import contribution_dir, problem_dir
from rp.ledger.events import make_event
from rp.ledger.operations import EventContext, accept_revision, bind_alias, record_events, reserve_alias
from rp.ledger.store import MemoryLedger
from rp.timeutil import FixedClock

ACTOR = {"kind": "app", "app_slug": "test-publisher"}


def _ledger(work: Path) -> MemoryLedger:
    lines = (work / "ledger" / "events.jsonl").read_text().splitlines()
    return MemoryLedger.from_events(json.loads(line) for line in lines)


def _save(work: Path, store: MemoryLedger) -> None:
    (work / "ledger" / "events.jsonl").write_bytes(store.export_jsonl())


def publish_contribution(work: Path, record: dict, files: dict[str, bytes], home_alias: str, when: str) -> str:
    store, ctx = _ledger(work), EventContext(ACTOR, FixedClock(when), "policy/1")
    policy = default_catalog().alias_policy
    cid, rid = record["contribution_id"], record["revision_id"]
    reservation = reserve_alias(store, lambda s: plan_contribution_alias(policy, s, home_problem_alias=home_alias,
                                                                          contribution_type=record["type"], entity_id=cid), ctx)
    bind_alias(store, reservation.alias, cid, ctx)
    fingerprint = scientific_fingerprint(record, manifest_from_blobs({p: (b, "100644") for p, b in files.items()}, record["artifacts"]))
    accept_revision(store, contribution_id=cid, revision_id=rid, expected_predecessor=record["expected_predecessor"],
                    scientific_fingerprint=fingerprint, authorization_binding=digest({"test": cid, "S": fingerprint}), ctx=ctx)
    folder = work / "research" / contribution_dir(record["home_problem_id"], cid, record["type"])
    for path, data in files.items():
        (folder / path).parent.mkdir(parents=True, exist_ok=True)
        (folder / path).write_bytes(data)
    (folder / "contribution.yaml").write_text(strict_yaml.dump(record))
    _save(work, store)
    return reservation.alias


def publish_subproblem(work: Path, record: dict, statement: bytes, parent_alias: str, when: str) -> str:
    store, ctx = _ledger(work), EventContext(ACTOR, FixedClock(when), "policy/1")
    policy = default_catalog().alias_policy
    pid, sid = record["problem_id"], record["statement_revision_id"]
    reservation = reserve_alias(store, lambda s: plan_subproblem_alias(policy, s, parent_alias=parent_alias, entity_id=pid), ctx)
    bind_alias(store, reservation.alias, pid, ctx)
    event = make_event(event_type="statement_revised", actor=ACTOR, targets=[pid, sid],
                       payload={"problem_id": pid, "statement_revision_id": sid, "predecessor": None},
                       scope={"problem_id": pid, "statement_revision_id": sid}, policy_version="policy/1", clock=ctx.clock)
    recorded = record_events(store, [event]).appended[0]
    folder = work / "research" / problem_dir(pid)
    folder.mkdir(parents=True)
    name = record["statement_artifact"]["path"]
    (folder / name).write_bytes(statement)
    (folder / "problem.yaml").write_text(strict_yaml.dump(record))
    descriptor = {"schema_version": 1, "statement_revision_id": sid, "problem_id": pid, "predecessor": None,
                  "statement_artifact": {"path": name, "digest": sha256_digest(statement), "bytes": len(statement)},
                  "change_kind": "initial", "change_note": "Test publication.", "source_commit": "0" * 40,
                  "recorded_at": recorded["recorded_at"]}
    (work / "ledger" / "statement-revisions" / f"{sid}.json").write_bytes(canonical_json(descriptor) + b"\n")
    _save(work, store)
    return reservation.alias
