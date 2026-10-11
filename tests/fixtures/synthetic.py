"""Deterministic synthetic research tree and ledger (§11 benchmark fixture).

    python -m tests.fixtures.synthetic --out /tmp/synthetic --seed 1
    python -m tests.fixtures.synthetic --golden    # print the golden summary for seed 1

The same seed always produces byte-identical output: identifiers come from a
seeded source, times from a fixed clock, and choices from a seeded RNG. All
content is synthetic; nothing is copied from the legacy repository. The tree
contains legacy-shaped cases that migration (milestone 2) must handle:
date-only FIRST_POSTED claims, unknown model versions, ``_v2``-style pairs
with unknown lineage, and a human_ai record from a "Human_Contribution" folder.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rp import strict_yaml
from rp.canonical import canonical_json, digest, sha256_digest
from rp.catalog import default_catalog
from rp.fingerprint import manifest_from_blobs, scientific_fingerprint
from rp.identity.aliases import plan_contribution_alias, plan_counter_alias, plan_external_alias, plan_subproblem_alias
from rp.identity.ids import SeededIdSource, new_id
from rp.identity.paths import contribution_dir, problem_dir
from rp.ledger.events import make_event
from rp.ledger.operations import EventContext, StateCache, accept_revision, bind_alias, record_events, reserve_alias
from rp.ledger.store import MemoryLedger
from rp.timeutil import DateClaim, FixedClock
from rp.vocab import CLAIM_TYPES, MODEL_ROLES, REVIEW_FINDINGS, TARGET_SCOPES

RESEARCH = "we-solve/research"
PUBLISHER = {"kind": "app", "app_slug": "we-solve-publisher"}
MSC_TOPS = ["05", "11", "52", "60", "91"]
JEL_CODES = ["C61", "C72", "C73", "D82", "D83"]
MODELS = [
    ("example-ai", "Example Model Pro", "example-model"),
    ("other-lab", "Other LM Ultra", "other-lm"),
    ("third-lab", "Third Reasoner", "third-reasoner"),
]
RIGHTS = {"licence": "CC-BY-4.0", "redistribution": "permitted"}
LEGACY_RIGHTS = {"licence": "LicenseRef-legacy-terms", "redistribution": "unclear"}


@dataclass
class Problem:
    problem_id: str
    statement_revision_id: str
    alias: str
    discipline: str
    record: dict[str, Any]


@dataclass
class Contribution:
    contribution_id: str
    revision_id: str
    alias: str
    home: Problem
    record: dict[str, Any]
    revisions: list[str] = field(default_factory=list)


class Generator:
    def __init__(self, seed: str, *, attempts: int, contributors: int, subproblems: int, reviews: int):
        self.seed = seed
        self.n_attempts = attempts
        self.n_contributors = contributors
        self.n_subproblems = subproblems
        self.n_reviews = reviews
        self.ids = SeededIdSource(f"synthetic/{seed}")
        self.rng = random.Random(f"synthetic/{seed}")
        self.ctx = EventContext(PUBLISHER, FixedClock("2026-10-01T00:00:00Z", step_seconds=37), "policy/1", self.ids)
        self.store = MemoryLedger()
        self.cache = StateCache(self.store)
        self.policy = default_catalog().alias_policy
        self.files: dict[str, bytes] = {}
        self.problems: list[Problem] = []
        self.contributions: list[Contribution] = []
        self.pr_number = 0
        self.people = [
            {
                "person_ref": new_id("person", self.ids),
                "github_id": 200000 + i,
                "login_at_event": f"contributor-{i:03d}",
                "display_name": f"Contributor {i:03d}",
            }
            for i in range(contributors)
        ]
        self.legacy_owner = {
            "person_ref": new_id("person", self.ids),
            "github_id": 199999,
            "login_at_event": "legacy-owner",
            "display_name": "Legacy repository owner",
        }

    # helpers ---------------------------------------------------------------

    def sha(self) -> str:
        return hashlib.sha256(self.ids.random_bytes()).hexdigest()[:40]

    def person(self, base: dict, roles: list[str], confirmation: str = "confirmed") -> dict:
        return {**base, "roles": roles, "authorship_confirmation": confirmation}

    def event(self, event_type: str, targets: list[str], payload: dict, scope: dict, **kwargs: Any) -> dict:
        return make_event(
            event_type=event_type,
            actor=kwargs.pop("actor", PUBLISHER),
            targets=targets,
            payload=payload,
            scope=scope,
            policy_version="policy/1",
            clock=self.ctx.clock,
            id_source=self.ids,
            **kwargs,
        )

    def record(self, *events: dict) -> None:
        record_events(self.store, list(events), cache=self.cache)

    def reserve_and_bind(self, plan, entity_id: str) -> str:
        reservation = reserve_alias(self.store, plan, self.ctx, cache=self.cache)
        bind_alias(self.store, reservation.alias, entity_id, self.ctx, cache=self.cache)
        return reservation.alias

    def model_use(self, *, unknown: bool) -> dict:
        provider, name, family = self.rng.choice(MODELS)
        return {
            "provider": provider,
            "declared_name": name,
            "family": family,
            "version": "unknown" if unknown else f"{family}-2026-0{self.rng.randint(1, 9)}-15",
            "role": self.rng.choice(MODEL_ROLES[:4]),
            "settings": None if unknown else {"reasoning": self.rng.choice(["low", "medium", "high"])},
            "generation_date": None if unknown else {"value": f"2026-0{self.rng.randint(1, 9)}", "precision": "month"},
            "provenance": {"level": "declared", "evidence": []},
        }

    def declarations(self, actor: str, source: str = "form_field") -> dict:
        entry = {"confirmed": True, "source": source, "actor": actor}
        return {"rights": dict(entry), "public_disclosure": dict(entry), "ai_disclosure": dict(entry)}

    def write_yaml(self, path: str, data: dict) -> None:
        self.files[path] = strict_yaml.dump(data).encode("utf-8")

    # problems --------------------------------------------------------------

    def add_problem(self, *, kind: str, discipline: str, classification: dict, plan, extra: dict) -> Problem:
        pid, stm = new_id("problem", self.ids), new_id("statement_revision", self.ids)
        alias = self.reserve_and_bind(lambda s: plan(s, pid), pid)
        record = {
            "schema_version": 1,
            "problem_id": pid,
            "statement_revision_id": stm,
            "expected_statement_predecessor": None,
            "title": f"Synthetic problem {alias}",
            "kind": kind,
            "disciplines": [{"discipline": discipline, "role": "primary"}],
            "classifications": [classification],
            "statement_artifact": {"path": "statement.md"},
            "external_ids": [],
            "sources": [],
            "relations": [],
            "rights": RIGHTS,
            **extra,
        }
        statement = f"# {alias}\n\nSynthetic statement {self.rng.randrange(10**6)}: determine whether $f(n) = O(n)$.\n".encode()
        base = str(problem_dir(pid))
        self.write_yaml(f"{base}/problem.yaml", record)
        self.files[f"{base}/statement.md"] = statement
        event = self.event(
            "statement_revised",
            [pid, stm],
            {"problem_id": pid, "statement_revision_id": stm, "predecessor": None},
            {"problem_id": pid, "statement_revision_id": stm},
        )
        self.record(event)
        self.files[f"ledger/statement-revisions/{stm}.json"] = canonical_json({
            "schema_version": 1, "statement_revision_id": stm, "problem_id": pid,
            "predecessor": None, "change_kind": "initial", "change_note": "Synthetic statement.",
            "statement_artifact": {"path": "statement.md", "digest": sha256_digest(statement), "bytes": len(statement)},
            "source_commit": hashlib.sha256(("synthetic/" + stm).encode()).hexdigest()[:40],
            "recorded_at": event["recorded_at"],
        }) + b"\n"
        problem = Problem(pid, stm, alias, discipline, record)
        self.problems.append(problem)
        return problem

    def proposer_block(self) -> dict:
        submitter = self.rng.choice(self.people)
        person = self.person(submitter, ["submission", "conceptualization"])
        return {
            "attribution": {"submitter": person, "humans": [person], "organisations": [], "contribution_mode": "human_only"},
            "model_uses": [],
        }

    def build_problems(self) -> None:
        for number in sorted(self.rng.sample(range(1, 1200), 40)):
            ext = str(number)
            commit = self.sha()
            problem = self.add_problem(
                kind="catalogued",
                discipline="mathematics",
                classification={"scheme": "msc2020", "code": f"{self.rng.choice(MSC_TOPS)}-XX"},
                plan=lambda s, pid, ext=ext: plan_external_alias(self.policy, s, scheme_id="erdos", external_identifier=ext, entity_id=pid),
                extra={
                    "external_ids": [{"scheme": "erdosproblems", "identifier": ext, "authority": "erdosproblems.com"}],
                    "sources": [
                        {
                            "authority": "erdosproblems.com",
                            "raw_status": self.rng.choice(["open", "falsifiable", "proved (Lean)"]),
                            "normalised_status": "open",
                            "snapshot": {"kind": "git_commit", "repository_url": "https://github.com/teorth/erdosproblems", "commit": commit},
                            "observed_at": {"value": "2026-09-23", "precision": "day"},
                            "provenance": {"recorded_by": "catalogue_sync"},
                        }
                    ],
                    "rights": {"licence": "LicenseRef-erdosproblems-terms", "redistribution": "link_only"},
                },
            )
            self.record(
                self.event(
                    "external_id_mapped",
                    [problem.problem_id],
                    {"entity_id": problem.problem_id, "scheme": "erdosproblems", "identifier": ext, "authority": "erdosproblems.com"},
                    {"scheme": "erdosproblems", "identifier": ext},
                )
            )
        ranks: dict[str, int] = {}
        for _ in range(20):
            jel = self.rng.choice(JEL_CODES)
            ranks[jel] = ranks.get(jel, 0) + 1
            ext = f"{jel}-{ranks[jel]}"
            self.add_problem(
                kind="catalogued",
                discipline="economics",
                classification={"scheme": "jel", "code": jel},
                plan=lambda s, pid, ext=ext: plan_external_alias(
                    self.policy, s, scheme_id="economics-legacy", external_identifier=ext, entity_id=pid
                ),
                extra={"external_ids": [{"scheme": "legacy-economics", "identifier": ext, "authority": "legacy-economics-catalogue"}]},
            )
        for i in range(10):
            self.add_problem(
                kind="literature",
                discipline="mathematics",
                classification={"scheme": "msc2020", "code": f"{self.rng.choice(MSC_TOPS)}-XX"},
                plan=lambda s, pid: plan_counter_alias(self.policy, s, prefix="MATH", entity_id=pid),
                extra={**self.proposer_block(), "citation": {"reference": {"kind": "arxiv", "value": f"2601.{10000 + i}"}, "locator": f"Problem {i + 1}"}},
            )
        for _ in range(5):
            self.add_problem(
                kind="proposed",
                discipline="computer-science",
                classification={"scheme": "acm-ccs2012", "code": "10003752"},
                plan=lambda s, pid: plan_counter_alias(self.policy, s, prefix="CS", entity_id=pid),
                extra={
                    **self.proposer_block(),
                    "proposal": {
                        "motivation": "Synthetic motivation.",
                        "relation_to_known": "Synthetic relation to known work.",
                        "elementary_checks": "Small cases checked.",
                        "literature_search": "Synthetic search description.",
                        "novelty_disclaimer_acknowledged": True,
                    },
                },
            )
        for _ in range(self.n_subproblems):
            parent = self.rng.choice([p for p in self.problems if p.discipline in ("mathematics", "economics")])
            classification = parent.record["classifications"][0]
            self.add_problem(
                kind="derived",
                discipline=parent.discipline,
                classification=classification,
                plan=lambda s, pid, parent=parent: plan_subproblem_alias(self.policy, s, parent_alias=parent.alias, entity_id=pid),
                extra={
                    **self.proposer_block(),
                    "relations": [{"type": "subproblem_of", "target_problem_id": parent.problem_id, "primary": True}],
                    "derivation": {
                        "parent_problem_id": parent.problem_id,
                        "nature": self.rng.choice(["restriction", "special_case", "step"]),
                        "parent_status_unchanged": True,
                    },
                },
            )

    # contributions ---------------------------------------------------------

    def target(self, problem: Problem) -> dict:
        return {
            "target_kind": "problem",
            "problem_id": problem.problem_id,
            "statement_revision_id": problem.statement_revision_id,
            "scope": self.rng.choice(TARGET_SCOPES),
        }

    def accept(self, contribution_id: str, revision_id: str, predecessor: str | None, record: dict) -> str:
        self.pr_number += 1
        alias = self.cache.refresh()[1].live_alias_of(contribution_id)
        files = self.artifact_bytes(alias, record)
        fingerprint = scientific_fingerprint(record, manifest_from_blobs({p: (b, "100644") for p, b in files.items()}, record["artifacts"]))
        label = accept_revision(
            self.store,
            contribution_id=contribution_id,
            revision_id=revision_id,
            expected_predecessor=predecessor,
            scientific_fingerprint=fingerprint,
            authorization_binding=digest({"pr": self.pr_number, "s": fingerprint}),
            ctx=self.ctx,
            cache=self.cache,
        )
        self.record(
            self.event(
                "revision_merged",
                [contribution_id, revision_id],
                {
                    "contribution_id": contribution_id,
                    "revision_id": revision_id,
                    "repository": RESEARCH,
                    "pull_request": self.pr_number,
                    "merged_source_commit": self.sha(),
                },
                {"contribution_id": contribution_id, "revision_id": revision_id},
            )
        )
        return label

    def add_contribution(self, *, ctype: str, home: Problem, body: dict, legacy: dict | None = None) -> Contribution:
        cid, rid = new_id("contribution", self.ids), new_id("revision", self.ids)
        alias = self.reserve_and_bind(
            lambda s: plan_contribution_alias(self.policy, s, home_problem_alias=home.alias, contribution_type=ctype, entity_id=cid), cid
        )
        record = {
            "schema_version": 1,
            "contribution_id": cid,
            "revision_id": rid,
            "expected_predecessor": None,
            "type": ctype,
            "home_problem_id": home.problem_id,
            **body,
        }
        intake = {"kind": "legacy_import" if legacy else "issue", "repository": RESEARCH}
        if not legacy:
            intake["number"] = 1000 + len(self.contributions)
        self.record(
            self.event(
                "contribution_submitted",
                [cid, rid],
                {"contribution_id": cid, "revision_id": rid, "intake_ref": intake},
                {"contribution_id": cid, "revision_id": rid},
            )
        )
        if legacy:
            claim = DateClaim(legacy["first_posted"], "day")
            self.record(
                self.event(
                    "date_declared",
                    [cid],
                    {"subject_id": cid, "kind": "first_posted", "claim": claim.to_json(), "source_text": f"FIRST_POSTED: {claim.value}"},
                    {"subject_id": cid, "kind": "first_posted"},
                    actor={"kind": "legacy_import"},
                    occurred_at=claim,
                    time_source="legacy_header",
                )
            )
        self.accept(cid, rid, None, record)
        contribution = Contribution(cid, rid, alias, home, record, [rid])
        if self.rng.random() < 0.1 and ctype != "legacy_record":
            rid2 = new_id("revision", self.ids)
            record = {**record, "revision_id": rid2, "expected_predecessor": rid, "title": record["title"] + " (revised)"}
            assert self.accept(cid, rid2, rid, record) == "r2"
            contribution.revision_id, contribution.record = rid2, record
            contribution.revisions.append(rid2)
        self.contributions.append(contribution)
        return contribution

    def attempt_body(self, home: Problem) -> dict:
        submitter = self.people[len(self.contributions) % len(self.people)]  # every contributor appears
        mode = self.rng.choices(["human_only", "ai_only", "human_ai"], weights=[2, 5, 3])[0]
        humans: list[dict] = []
        if mode != "ai_only":
            humans = [self.person(submitter, ["investigation", "writing_original_draft"])]
            if self.rng.random() < 0.3:
                co = self.rng.choice([p for p in self.people if p is not submitter])
                humans.append(self.person(co, ["validation"], "listed_by_submitter"))
        model_uses = [] if mode == "human_only" else [self.model_use(unknown=self.rng.random() < 0.4)]
        targets = [self.target(home)]
        if self.rng.random() < 0.05:
            other = self.rng.choice([p for p in self.problems if p is not home])
            targets.append(self.target(other))
        claim_type = self.rng.choice(CLAIM_TYPES)
        claim = {"type": claim_type, "scope_statement": f"Synthetic {claim_type} claim.", "assumptions": [], "limitations": []}
        if claim_type == "partial_result" and self.rng.random() < 0.5:
            claim["completion_estimate"] = {"percent": self.rng.randrange(5, 95, 5), "justification": "Synthetic estimate."}
        artifacts = [{"role": "manuscript", "location": "in_repository", "path": "files/attempt.md", "media_type": "text/markdown"}]
        if self.rng.random() < 0.1:
            artifacts.append(
                {"role": "code", "location": "external_pinned", "external": {"url": "https://github.com/example/code", "pin": {"kind": "git_commit", "value": self.sha()}}}
            )
        return {
            "targets": targets,
            "title": f"Synthetic attempt on {home.alias}",
            "profiles": [{"id": "mathematical_argument", "version": 1, "required": True}],
            "claim": claim,
            "attribution": {"submitter": self.person(submitter, ["submission"]), "humans": humans, "organisations": [], "contribution_mode": mode},
            "model_uses": model_uses,
            "lineage": [],
            "artifacts": artifacts,
            "rights": RIGHTS,
            "declarations": self.declarations(submitter["person_ref"]),
        }

    def legacy_body(self, home: Problem, *, pair_of: Contribution | None, human_folder: bool) -> dict:
        status = self.rng.choice(["solved", "partial", "unresolved"])
        claim_type = {"solved": "full_solution", "partial": "partial_result", "unresolved": "exploration"}[status]
        owner = self.person(self.legacy_owner, ["submission"])
        humans, mode = [], "ai_only"
        extensions = {}
        if human_folder:
            # A "Human_Contribution" folder does not make the work human-only.
            contributor = self.rng.choice(self.people)
            humans, mode = [self.person(contributor, ["investigation"], "listed_by_submitter")], "human_ai"
            extensions = {"org.we-solve.legacy": {"folder": "Human_Contribution"}}
        lineage = []
        if pair_of is not None:
            lineage.append(
                {
                    "relation": "possible_revision_of",
                    "contribution_id": pair_of.contribution_id,
                    "revision_id": None,
                    "lineage_status": "unknown",
                    "note": "_v2 file name; not evidence of revision lineage.",
                }
            )
        stem = f"{home.alias}{'_v2' if pair_of else ''}"
        body = {
            "targets": [self.target(home)],
            "title": f"Legacy attempt {stem}",
            "profiles": [{"id": "mathematical_argument", "version": 1, "required": True}],
            "claim": {"type": claim_type, "scope_statement": f"Legacy ATTEMPT_STATUS: {status} (a claim, not a status).", "assumptions": [], "limitations": []},
            "attribution": {"submitter": owner, "humans": humans, "organisations": [], "contribution_mode": mode},
            "model_uses": [self.model_use(unknown=True)],
            "lineage": lineage,
            "artifacts": [{"role": "manuscript_source", "location": "in_repository", "path": f"files/{stem}.tex", "media_type": "application/x-tex"}],
            "rights": LEGACY_RIGHTS,
            "declarations": self.declarations(self.legacy_owner["person_ref"], source="legacy_import"),
        }
        if extensions:
            body["extensions"] = extensions
        return body

    @staticmethod
    def artifact_bytes(alias: str, record: dict) -> dict[str, bytes]:
        return {a["path"]: f"Synthetic content of {alias} ({a['path']}).\n".encode()
                for a in record["artifacts"] if a["location"] == "in_repository"}

    def write_contribution(self, c: Contribution) -> None:
        base = str(contribution_dir(c.home.problem_id, c.contribution_id, c.record["type"]))
        self.write_yaml(f"{base}/contribution.yaml", c.record)
        for path, content in self.artifact_bytes(c.alias, c.record).items():
            self.files[f"{base}/{path}"] = content

    def build_contributions(self) -> None:
        n_legacy = self.n_attempts // 10
        weights = [3 if p.record["kind"] == "catalogued" else 1 for p in self.problems]
        for _ in range(self.n_attempts - n_legacy):
            home = self.rng.choices(self.problems, weights=weights)[0]
            ctype = "counterexample" if self.rng.random() < 0.1 else "attempt"
            self.add_contribution(ctype=ctype, home=home, body=self.attempt_body(home))
        econ = [p for p in self.problems if p.discipline == "economics"]
        previous: Contribution | None = None
        for i in range(n_legacy):
            pair = previous is not None and i % 5 == 1
            home = previous.home if pair else self.rng.choice(econ if i % 2 else self.problems)
            body = self.legacy_body(home, pair_of=previous if pair else None, human_folder=(i == 3))
            day = f"2026-{self.rng.randint(1, 9):02d}-{self.rng.randint(1, 28):02d}"
            previous = self.add_contribution(ctype="legacy_record", home=home, body=body, legacy={"first_posted": day})
        attempts = list(self.contributions)
        for _ in range(self.n_reviews):
            target = self.rng.choice(attempts)
            reviewer = self.rng.choice(self.people)
            finding = self.rng.choice(REVIEW_FINDINGS)
            body = {
                "targets": [{"target_kind": "contribution_revision", "contribution_id": target.contribution_id, "revision_id": target.revision_id}],
                "title": f"Review of {target.alias}",
                "profiles": [{"id": "review", "version": 1, "required": True}],
                "attribution": {
                    "submitter": self.person(reviewer, ["submission", "validation"]),
                    "humans": [self.person(reviewer, ["validation"])],
                    "organisations": [],
                    "contribution_mode": "human_only",
                },
                "model_uses": [],
                "lineage": [],
                "artifacts": [{"role": "manuscript", "location": "in_repository", "path": "files/review.md", "media_type": "text/markdown"}],
                "rights": RIGHTS,
                "declarations": self.declarations(reviewer["person_ref"]),
                "review": {"finding": finding, "checked_scope": "Synthetic scope.", "evidence": "Synthetic evidence.", "conflicts_of_interest": "None declared."},
            }
            self.add_contribution(ctype="review", home=target.home, body=body)

    def build_snapshot(self) -> None:
        snapshot_id = new_id("publication_snapshot", self.ids)
        self.record(
            self.event("snapshot_built", [snapshot_id], {"snapshot_id": snapshot_id, "snapshot_digest": digest(sorted(self.files))}, {"snapshot_id": snapshot_id}),
            self.event(
                "snapshot_activated",
                [snapshot_id],
                {"snapshot_id": snapshot_id, "previous_snapshot_id": None, "deployment": {"repository": "we-solve/we-solve.github.io", "run_id": 1}},
                {"snapshot_id": snapshot_id, "activation": 1},
            ),
        )

    def run(self) -> dict[str, Any]:
        self.build_problems()
        self.build_contributions()
        for c in self.contributions:
            self.write_contribution(c)
        self.build_snapshot()
        ledger_bytes = self.store.export_jsonl()
        self.files["ledger/events.jsonl"] = ledger_bytes
        state = self.cache.refresh()[1]
        kinds: dict[str, int] = {}
        for p in self.problems:
            kinds[p.record["kind"]] = kinds.get(p.record["kind"], 0) + 1
        types: dict[str, int] = {}
        for c in self.contributions:
            types[c.record["type"]] = types.get(c.record["type"], 0) + 1
        contributors = {p["person_ref"] for c in self.contributions for p in [c.record["attribution"]["submitter"], *c.record["attribution"]["humans"]]}
        return {
            "seed": self.seed,
            "tree_digest": tree_digest(self.files),
            "ledger_head": self.store.read()[0],
            "files": len(self.files),
            "events": ledger_bytes.count(b"\n"),
            "problems": dict(sorted(kinds.items())),
            "contributions": dict(sorted(types.items())),
            "contributors": len(contributors),
            "aliases": len(state.aliases),
            "revised": sum(1 for c in self.contributions if len(c.revisions) > 1),
        }


def tree_digest(files: dict[str, bytes]) -> str:
    return digest([[path, sha256_digest(content)] for path, content in sorted(files.items())])


def generate(out: Path | None = None, seed: str = "1", *, attempts: int = 500, contributors: int = 200, subproblems: int = 30, reviews: int = 60) -> dict[str, Any]:
    gen = Generator(seed, attempts=attempts, contributors=contributors, subproblems=subproblems, reviews=reviews)
    summary = gen.run()
    if out is not None:
        for path, content in gen.files.items():
            target = Path(out) / ("research" if not path.startswith("ledger/") else "") / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--seed", default="1")
    parser.add_argument("--golden", action="store_true", help="print the summary as canonical JSON")
    args = parser.parse_args()
    summary = generate(args.out, args.seed)
    if args.golden:
        print(canonical_json(summary).decode())
    else:
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
