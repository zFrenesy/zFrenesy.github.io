"""Idempotent legacy importer (spec §12, docs/adr/0009 and 0010).

    python -m rp.migration.importer --legacy <legacy-clone> --out ~/we-solve-work

Reads the legacy repository at the pinned commit and writes:

    <out>/research/problems/<shard>/<problem-id>/problem.yaml, statement.tex|.md
    <out>/research/problems/<shard>/<problem-id>/contributions/<id>/contribution.yaml, files/...
    <out>/research/migration/legacy-b1f6331/  mapping.jsonl, inventory.json, inventory.md,
                                              owner-declarations.yaml, github-snapshot.json
    <out>/ledger/events.jsonl, ledger/statement-revisions/<stm>.json

Identity is retained: an existing mapping and ledger in ``<out>`` are read first
and every identifier, alias and event is reused, so a re-run appends nothing and
rewrites identical bytes. Every record is schema-validated before it is written;
any error stops the import (fail closed).
"""

from __future__ import annotations

import argparse
import csv
import html
import io
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rp import PACKAGE_ROOT, strict_yaml
from rp.canonical import canonical_json, digest, sha256_digest
from rp.catalog import Catalog, default_catalog
from rp.fingerprint import manifest_from_blobs, scientific_fingerprint
from rp.identity.aliases import plan_contribution_alias, plan_external_alias
from rp.identity.ids import IdSource, new_id
from rp.identity.paths import contribution_dir, problem_dir
from rp.ledger.events import make_event
from rp.ledger.operations import EventContext, StateCache, accept_revision, bind_alias, record_events, reserve_alias
from rp.ledger.store import MemoryLedger
from rp.migration.inventory import Inventory, InventoryEntry, build_inventory
from rp.migration.legacy_git import LEGACY_COMMIT, LegacyRepo
from rp.migration.reviews import ReviewHistory, review_history
from rp.render import legacy_prep
from rp.timeutil import Clock, DateClaim, SystemClock
from rp.validation.records import validate_record

__all__ = ["ImportResult", "LegacyImporter", "IMPORT_ID"]

IMPORT_ID = "legacy-b1f6331"
LEGACY_REPOSITORY = "mehmetmars7/Erdosproblems-llm-hunter"
LEGACY_URL = "https://github.com/mehmetmars7/Erdosproblems-llm-hunter"
LEGACY_OWNER = "mehmetmars7"
CONFIG = PACKAGE_ROOT / "migration" / "legacy"
IMPORTER_ACTOR = {"kind": "legacy_import"}
DECLARATION_NOTE = f"Owner declaration, 2026-10-11: migration/{IMPORT_ID}/owner-declarations.yaml"
EXTENSION = "org.we-solve.legacy"
_SAFE_SEGMENT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]*")

ERDOS_STATUS = {
    "open": "open", "open (Lean)": "open", "falsifiable": "open", "verifiable": "open", "decidable": "open",
    "proved": "proved", "proved (Lean)": "proved", "disproved": "disproved", "disproved (Lean)": "disproved",
    "solved": "solved", "solved (Lean)": "solved", "independent": "independent",
    "partially solved": "partially_solved", "not provable": "other", "not disprovable": "other",
}
TOP_STATUS = {"open": "open", "partially_solved": "partially_solved", "solved": "solved"}
CLAIMS = {"solved": "full_solution", "partial": "partial_result", "unresolved": "exploration"}
# External codes that are references, not identifiers: UnsolvedMath reuses public codes
# for different records, so they are shown but never mapped as identity (ledger).
NON_IDENTITY_SCHEMES = frozenset({"unsolvedmath-code"})
CONTRIBUTION_CLASSES = ("attempt", "reused_writeup", "statement_copy", "external_claim_summary", "human_contribution")


class ImportError_(RuntimeError):
    pass


@dataclass
class Problem:
    key: str
    alias: str
    problem_id: str
    statement_revision_id: str
    record: dict[str, Any]
    statement_name: str
    statement_bytes: bytes
    scheme: str
    external_identifier: str
    external_maps: list[tuple[str, str, str]]
    collection: str
    legacy_ids: list[str] = field(default_factory=list)


@dataclass
class ImportResult:
    counts: dict[str, int]
    files_written: int
    events: int
    ledger_head: str
    uncertain: int


def _load_config(name: str) -> Any:
    return strict_yaml.load((CONFIG / name).read_bytes())


def _safe_name(name: str, taken: set[str]) -> str:
    safe = name if _SAFE_SEGMENT.fullmatch(name) else re.sub(r"[^A-Za-z0-9._]+", "-", name).strip("-.") or "file"
    if not _SAFE_SEGMENT.fullmatch(safe):
        safe = "f-" + safe
    base, dot, ext = safe.rpartition(".")
    candidate, n = safe, 2
    while candidate in taken:
        candidate = f"{base}-{n}.{ext}" if dot else f"{safe}-{n}"
        n += 1
    taken.add(candidate)
    return candidate


class Mapping:
    """Retained identity mapping (migration/<import>/mapping.jsonl)."""

    def __init__(self, path: Path, id_source: IdSource | None):
        self.path = path
        self.id_source = id_source
        self.records: dict[str, dict[str, Any]] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                record = json.loads(line)
                self.records[record["key"]] = record

    def ids(self, key: str, **kinds: str) -> dict[str, str]:
        """Existing identifiers for ``key``, or new ones of the given kinds (field -> id kind)."""
        record = self.records.setdefault(key, {"key": key})
        for name, kind in kinds.items():
            if name not in record:
                record[name] = new_id(kind, self.id_source)
        return {name: record[name] for name in kinds}

    def update(self, key: str, **fields: Any) -> None:
        self.records.setdefault(key, {"key": key}).update(fields)

    def dump(self) -> bytes:
        return b"".join(canonical_json(self.records[k]) + b"\n" for k in sorted(self.records))


class LegacyImporter:
    def __init__(
        self,
        repo: LegacyRepo,
        out: Path,
        *,
        catalog: Catalog | None = None,
        id_source: IdSource | None = None,
        clock: Clock | None = None,
        snapshot: dict[str, Any] | None = None,
    ):
        self.repo = repo
        self.out = Path(out)
        self.research = self.out / "research"
        self.migration_dir = self.research / "migration" / IMPORT_ID
        self.catalog = catalog or default_catalog()
        self.policy = self.catalog.alias_policy
        self.clock = clock or SystemClock()
        self.id_source = id_source
        self.snapshot = snapshot if snapshot is not None else json.loads((CONFIG / "github-snapshot.json").read_text())
        self.models = _load_config("models.yaml")
        self.overrides = _load_config("overrides.yaml")
        self.mapping = Mapping(self.migration_dir / "mapping.jsonl", id_source)
        events_path = self.out / "ledger" / "events.jsonl"
        existing = [json.loads(line) for line in events_path.read_text().splitlines()] if events_path.exists() else []
        self.store = MemoryLedger.from_events(existing)
        self.cache = StateCache(self.store)
        self.ctx = EventContext(IMPORTER_ACTOR, self.clock, "policy/1", id_source)
        self.files: dict[str, bytes] = {}
        self.problems: dict[str, Problem] = {}
        self.people: dict[str, dict[str, Any]] = {}
        self.uncertain = 0
        self.counts: dict[str, int] = defaultdict(int)

    # ------------------------------------------------------------------ helpers

    def _source(self, path: str | None = None, blob: str | None = None) -> dict[str, Any]:
        source: dict[str, Any] = {"repository": LEGACY_REPOSITORY, "repository_id": self.snapshot.get("repository_id"), "commit": self.repo.commit}
        if path is not None:
            source["path"] = path
        if blob is not None:
            source["blob"] = blob
        return source

    def _record_events(self, events: list[dict]) -> list[dict]:
        """Append (or find, on a re-run) these events; returns the recorded versions."""
        result = record_events(self.store, events, cache=self.cache)
        recorded = {e["idempotency_key"]: e for e in (*result.appended, *result.existing)}
        return [recorded[e["idempotency_key"]] for e in events]

    def _event(self, event_type: str, targets: list[str], payload: dict, scope: dict, **kwargs: Any) -> dict:
        return make_event(
            event_type=event_type,
            actor=kwargs.pop("actor", IMPORTER_ACTOR),
            targets=targets,
            payload=payload,
            scope={"import": IMPORT_ID, **scope},
            policy_version="policy/1",
            clock=self.clock,
            id_source=self.id_source,
            **kwargs,
        )

    def _reserve(self, plan, entity_id: str) -> str:
        reservation = reserve_alias(self.store, plan, self.ctx, cache=self.cache)
        bind_alias(self.store, reservation.alias, entity_id, self.ctx, cache=self.cache)
        return reservation.alias

    def _validate(self, record_type: str, record: dict, where: str) -> None:
        errors = [i for i in validate_record(record_type, record, catalog=self.catalog) if i.severity == "error"]
        if errors:
            raise ImportError_(f"{where}: invalid {record_type}: " + "; ".join(str(e) for e in errors[:5]))

    def person(self, *, login: str | None, display_name: str, roles: list[str], confirmation: str) -> dict[str, Any]:
        key = f"person:github:{login}" if login else f"person:name:{display_name}"
        ref = self.mapping.ids(key, entity_id="person")["entity_id"]
        github_id = (self.snapshot.get("users", {}).get(login) or {}).get("id") if login else None
        self.mapping.update(key, kind="person", login=login, display_name=display_name, github_id=github_id)
        return {
            "person_ref": ref,
            "github_id": github_id,
            "login_at_event": login,
            "display_name": display_name,
            "roles": roles,
            "authorship_confirmation": confirmation,
        }

    def owner(self, roles: list[str] | None = None) -> dict[str, Any]:
        return self.person(login=LEGACY_OWNER, display_name=f"{LEGACY_OWNER} (legacy repository owner)", roles=roles or ["submission"], confirmation="confirmed")

    # ------------------------------------------------------------------ problems

    def _catalogues(self, inv: Inventory) -> dict[str, Any]:
        def blob(path: str) -> bytes:
            entry = next(e for e in inv.entries if e.path == path)
            return inv.contents[entry.blob]

        return {
            "erdos_status": json.loads(blob("lists/erdos_status.json")),
            "erdos_csv": list(csv.DictReader(io.StringIO(blob("lists/erdos_problems.csv").decode("utf-8")))),
            "mo_csv": list(csv.DictReader(io.StringIO(blob("lists/mo_problems.csv").decode("utf-8")))),
            "top": json.loads(blob("lists/unsolvedmath/problems.json")),
            "economics": json.loads(blob("lists/economics/problems.json"))["problems"],
            "openai": json.loads(blob("lists/openai_math/manifest.json")),
        }

    def _add_problem(self, key: str, *, collection: str, scheme: str, ext: str, title: str, disciplines: list[dict],
                     classifications: list[dict], topics: list[str], statement: tuple[str, bytes], external_ids: list[dict],
                     sources: list[dict], rights: dict, extension: dict, legacy_ids: list[str] | None = None) -> None:
        ids = self.mapping.ids(f"problem:{key}", problem_id="problem", statement_revision_id="statement_revision")
        record: dict[str, Any] = {
            "schema_version": 1,
            "problem_id": ids["problem_id"],
            "statement_revision_id": ids["statement_revision_id"],
            "expected_statement_predecessor": None,
            "title": title,
            "kind": "catalogued",
            "disciplines": disciplines,
        }
        if topics:
            record["topics"] = topics
        record.update(
            classifications=classifications,
            statement_artifact={"path": statement[0]},
            external_ids=external_ids,
            sources=sources,
            relations=[],
            rights=rights,
            extensions={EXTENSION: extension},
        )
        self.problems[key] = Problem(
            key, "", ids["problem_id"], ids["statement_revision_id"], record, statement[0], statement[1], scheme, ext,
            [(x["scheme"], x["identifier"], x["authority"]) for x in external_ids if x["scheme"] not in NON_IDENTITY_SCHEMES],
            collection, legacy_ids or [],
        )

    def build_problems(self, inv: Inventory) -> None:
        cat = self._catalogues(inv)
        referenced: dict[str, set[str]] = defaultdict(set)
        for entry in inv.entries:
            if entry.problem_key and entry.cls in CONTRIBUTION_CLASSES:
                collection, ident = entry.problem_key.split(":", 1)
                referenced[collection].add(ident)
        observed = DateClaim(cat["erdos_status"]["checked_at"], "instant").to_json()
        teorth = {"kind": "git_commit", "repository_url": "https://github.com/teorth/erdosproblems",
                  "commit": cat["erdos_status"]["source_commit"], "path": "data/problems.yaml"}
        legacy_list = lambda path: {"kind": "git_commit", "repository_url": LEGACY_URL, "commit": self.repo.commit, "path": path}  # noqa: E731
        legacy_day = DateClaim(self.repo.path_log("lists")[-1][1][:10], "day").to_json()

        erdos_numbers = set(cat["erdos_status"]["problems"]) | {r["number"] for r in cat["erdos_csv"]} | referenced["erdos"]
        for n in sorted(erdos_numbers, key=int):
            status = cat["erdos_status"]["problems"].get(n)
            url = f"https://www.erdosproblems.com/{n}"
            stub = f"# Erdős Problem #{n}\n\nThe statement is maintained at [erdosproblems.com/{n}]({url}) and is not reproduced here.\n"
            sources = []
            if status:
                sources.append({"authority": "erdosproblems.com", "source_url": url, "raw_status": status["status"],
                                "normalised_status": ERDOS_STATUS.get(status["status"], "other"), "snapshot": teorth,
                                "observed_at": observed, "provenance": {"recorded_by": "legacy_import"}})
            self._add_problem(
                f"erdos:{n}", collection="erdos", scheme="erdos", ext=n, title=f"Erdős Problem #{n}",
                disciplines=[{"discipline": "mathematics", "role": "primary"}], classifications=[], topics=[],
                statement=("statement.md", stub.encode()),
                external_ids=[{"scheme": "erdosproblems", "identifier": n, "authority": "erdosproblems.com", "url": url}],
                sources=sources,
                rights={"licence": "LicenseRef-erdosproblems", "redistribution": "link_only",
                        "notes": "The statement is maintained at erdosproblems.com and is linked, not reproduced."},
                extension={"collection": "erdos", "status_snapshot": status or None},
            )
            if not status:
                self.mapping.update(f"problem:erdos:{n}", uncertainty=["no status in the pinned erdos_status.json"])

        econ_by_id = {p["id"]: p for p in cat["economics"]}
        statements = {e.problem_key.split(":", 1)[1]: e for e in inv.by_class("statement") if e.collection == "economics"}
        for ident in sorted(set(econ_by_id) | referenced["economics"]):
            meta = econ_by_id.get(ident)
            entry = statements.get(ident)
            if meta is None or entry is None:
                raise ImportError_(f"economics problem {ident} has no registry entry or statement")
            self._add_problem(
                f"economics:{ident}", collection="economics", scheme="economics-legacy", ext=ident, title=meta["title"],
                disciplines=[{"discipline": "economics", "role": "primary"}],
                classifications=[{"scheme": "jel", "code": meta["jel_code"]}], topics=[],
                statement=("statement.tex", inv.contents[entry.blob]),
                external_ids=[{"scheme": "legacy-economics", "identifier": ident, "authority": "legacy-economics-catalogue"}],
                sources=[],
                rights={"licence": "CC-BY-4.0", "redistribution": "permitted", "holders": [f"{LEGACY_OWNER} (legacy repository owner)"], "notes": DECLARATION_NOTE},
                extension={"collection": "economics", "source_path": entry.path, "source_blob": entry.blob,
                           "source_id": meta["source_id"], "source_catalog": meta["source_catalog"], "initial_rank": meta["initial_rank"]},
            )

        top_by_id = {str(p["id"]): p for p in cat["top"]}
        definitions = {e.problem_key.split(":", 1)[1]: e for e in inv.by_class("statement") if e.collection == "top"}
        for ident in sorted(set(top_by_id) | referenced["top"], key=int):
            meta = top_by_id.get(ident)
            entry = definitions.get(ident)
            if meta is None or entry is None:
                raise ImportError_(f"Top Open Problems record {ident} has no catalogue entry or statement")
            code = meta.get("problem_number") or ""
            local = code.startswith("LOCAL-")
            category = meta["category"]["slug"]
            disciplines = [{"discipline": "computer-science" if category == "computer-science" else "mathematics", "role": "primary"}]
            if category == "physics":
                disciplines.append({"discipline": "mathematical-physics", "role": "secondary"})
            external = [{"scheme": "legacy-top-open-problems", "identifier": ident, "authority": "legacy-top-open-problems-catalogue"}]
            if not local:
                external.append({"scheme": "unsolvedmath-id", "identifier": ident, "authority": "unsolvedmath.com"})
                if code:
                    ext = {"scheme": "unsolvedmath-code", "identifier": code, "authority": "unsolvedmath.com"}
                    if meta.get("external_url"):
                        ext["url"] = meta["external_url"]
                    external.append(ext)
            sa = code.startswith("OWR-")
            notes = DECLARATION_NOTE + ("; derived from Oberwolfach Reports material (CC BY-SA 4.0), so ShareAlike applies" if sa else "")
            self._add_problem(
                f"top:{ident}", collection="top", scheme="top-open-problems", ext=ident, title=meta["title"],
                disciplines=disciplines, classifications=[], topics=[category],
                statement=("statement.tex", inv.contents[entry.blob]),
                external_ids=external,
                sources=[{"authority": "legacy-top-open-problems-catalogue" if local else "unsolvedmath.com",
                          **({"source_url": meta["external_url"]} if meta.get("external_url") else {}),
                          "raw_status": meta["status"], "normalised_status": TOP_STATUS.get(meta["status"], "other"),
                          "snapshot": legacy_list("lists/unsolvedmath/problems.json"), "observed_at": legacy_day,
                          "provenance": {"recorded_by": "legacy_import"}}],
                rights={"licence": "CC-BY-SA-4.0" if sa else "CC-BY-4.0", "redistribution": "permitted",
                        "holders": [f"{LEGACY_OWNER} (legacy repository owner)"],
                        "third_party": [{"description": "Catalogue metadata from UnsolvedMath by Ulam AI and the UnsolvedMath Contributors, adapted",
                                         "licence": "CC-BY-4.0", "source_url": "https://huggingface.co/datasets/ulamai/UnsolvedMath"}],
                        "notes": notes},
                extension={"collection": "top", "source_path": entry.path, "source_blob": entry.blob, "problem_number": code or None,
                           "category": category, "summary": meta.get("statement"), "legacy_ids": meta.get("legacy_ids", [])},
                legacy_ids=meta.get("legacy_ids", []),
            )

        mo_rows: dict[str, dict] = {}
        for row in cat["mo_csv"]:
            mo_rows.setdefault(row["question_id"], row)
        for ident in sorted(set(mo_rows) | referenced["mo"], key=int):
            row = mo_rows.get(ident)
            url = row["link"] if row else f"https://mathoverflow.net/questions/{ident}"
            title = html.unescape(row["title"]) if row else f"MathOverflow question {ident}"
            tags = row["tags"].split(";") if row and row.get("tags") else []
            self._add_problem(
                f"mo:{ident}", collection="mo", scheme="mathoverflow", ext=ident, title=title,
                disciplines=[{"discipline": "mathematics", "role": "primary"}], classifications=[],
                topics=sorted({re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-") for t in tags if t})[:20],
                statement=("statement.md", f"# {title}\n\nThis question is on [MathOverflow]({url}) and is not reproduced here.\n".encode()),
                external_ids=[{"scheme": "mathoverflow", "identifier": ident, "authority": "mathoverflow.net", "url": url}],
                sources=[],
                rights={"licence": "CC-BY-SA-4.0", "redistribution": "link_only",
                        "notes": "MathOverflow content is CC BY-SA 4.0; the question is linked and its title is reproduced with attribution."},
                extension={"collection": "mo", "tags": tags, "score": row.get("score") if row else None},
            )
            if not row:
                self.mapping.update(f"problem:mo:{ident}", uncertainty=["question referenced by an attempt but absent from lists/mo_problems.csv"])

    def register_problems(self) -> None:
        for key, problem in self.problems.items():
            record = problem.record
            self._validate("problem", record, key)
            pid = problem.problem_id
            problem.alias = self._reserve(
                lambda s, p=problem: plan_external_alias(self.policy, s, scheme_id=p.scheme, external_identifier=p.external_identifier, entity_id=p.problem_id),
                pid,
            )
            events = [self._event("statement_revised", [pid, problem.statement_revision_id],
                                  {"problem_id": pid, "statement_revision_id": problem.statement_revision_id, "predecessor": None},
                                  {"problem_id": pid, "statement_revision_id": problem.statement_revision_id})]
            for scheme, ident, authority in problem.external_maps:
                events.append(self._event("external_id_mapped", [pid], {"entity_id": pid, "scheme": scheme, "identifier": ident, "authority": authority},
                                          {"scheme": scheme, "identifier": ident}))
            recorded = self._record_events(events)
            base = str(problem_dir(pid))
            self.files[f"research/{base}/problem.yaml"] = strict_yaml.dump(record).encode("utf-8")
            self.files[f"research/{base}/{problem.statement_name}"] = problem.statement_bytes
            statement_revision = {
                "schema_version": 1,
                "statement_revision_id": problem.statement_revision_id,
                "problem_id": pid,
                "predecessor": None,
                "statement_artifact": {"path": problem.statement_name, "digest": sha256_digest(problem.statement_bytes), "bytes": len(problem.statement_bytes)},
                "change_kind": "import",
                "change_note": f"Imported from {LEGACY_REPOSITORY} at {self.repo.commit[:12]}.",
                "source_commit": self.repo.commit,
                "recorded_at": recorded[0]["recorded_at"],
            }
            self._validate("statement_revision", statement_revision, key)
            self.files[f"ledger/statement-revisions/{problem.statement_revision_id}.json"] = canonical_json(statement_revision) + b"\n"
            self.mapping.update(f"problem:{key}", kind="problem", alias=problem.alias, source=self._source(), legacy_ids=problem.legacy_ids)
            self.counts[f"problems_{problem.collection}"] += 1

    # ------------------------------------------------------------------ contributions

    def _model_use(self, folder_key: str, headers_model: str | None, role: str = "generated_draft") -> dict[str, Any]:
        table = self.models["folders"].get(folder_key)
        if table is None:
            raise ImportError_(f"no owner-confirmed model entry for legacy folder {folder_key}")
        return {
            "provider": table["provider"],
            "declared_name": headers_model or table["declared_name"],
            "family": table.get("family"),
            "version": "unknown",
            "role": role,
            "settings": dict(table["settings"]) if table.get("settings") else None,
            "generation_date": None,
            "provenance": {"level": "declared", "evidence": [{"kind": "statement", "note": "MODEL header" if headers_model else self.models["evidence"]}]},
        }

    def _declarations(self, actor: str) -> dict[str, Any]:
        entry = {"confirmed": True, "source": "legacy_import", "actor": actor}
        return {"rights": dict(entry), "public_disclosure": dict(entry), "ai_disclosure": dict(entry)}

    def _rights(self, third_party: list[dict] | None = None) -> dict[str, Any]:
        rights: dict[str, Any] = {"licence": "CC-BY-4.0", "redistribution": "permitted", "holders": [f"{LEGACY_OWNER} (legacy repository owner)"], "notes": DECLARATION_NOTE}
        if third_party:
            rights["third_party"] = third_party
        return rights

    def build_contributions(self, inv: Inventory, histories: dict[str, ReviewHistory]) -> None:
        entries = [e for e in inv.entries if e.cls in CONTRIBUTION_CLASSES]
        by_path = {e.path: e for e in entries}
        keys = {e.path: self.mapping.ids(f"contribution:{e.path}", contribution_id="contribution", revision_id="revision") for e in entries}
        first_added = self.repo.first_added("attacks")
        aliases_for_legacy_paths = {
            "attacks/open_problems/erdos/": ["attacks/erdos/"],
            "attacks/open_problems/top_problems/gpt_6_astra_ultra/": ["attacks/open_problems/top_problems/GPT_6_Astra_Ultra/"],
        }

        def added(path: str) -> str | None:
            candidates = [path]
            for prefix, olds in aliases_for_legacy_paths.items():
                if path.startswith(prefix):
                    candidates += [old + path[len(prefix):] for old in olds]
            found = [first_added[c] for c in candidates if c in first_added]
            return min(found) if found else None

        def current_path(path: str) -> str:
            for collection in ("erdos", "mo"):
                if path.startswith(f"attacks/{collection}/"):
                    return f"attacks/open_problems/{collection}/" + path[len(f"attacks/{collection}/"):]
            return path

        def lineage(entry: InventoryEntry) -> list[dict]:
            out = []
            name = entry.path.rsplit("/", 1)[1]
            headers = entry.headers
            revision_of = headers.first("REVISION_OF") if headers else None
            if revision_of:
                source = f"attacks/open_problems/{entry.path.split('/')[2]}/{revision_of}"
                if source in keys:
                    out.append({"relation": "derivative_of", "contribution_id": keys[source]["contribution_id"],
                                "revision_id": keys[source]["revision_id"], "lineage_status": "known", "note": f"REVISION_OF: {revision_of}"})
            elif entry.version and entry.version > 1:
                base = re.sub(r"_v[0-9]+\.tex$", ".tex", entry.path)
                if base in keys:
                    out.append({"relation": "possible_revision_of", "contribution_id": keys[base]["contribution_id"], "revision_id": None,
                                "lineage_status": "unknown", "note": f"{name}: a _v suffix in the same folder is not evidence of revision lineage."})
            if entry.cls == "reused_writeup":
                meta = entry.headers.data["COLLECTION_METADATA"]
                source = current_path(meta["primary_source"])
                if source in keys:
                    out.append({"relation": "reuses", "contribution_id": keys[source]["contribution_id"], "revision_id": keys[source]["revision_id"],
                                "lineage_status": "known", "note": f"COLLECTION_METADATA primary_source: {meta['primary_source']}"})
                else:
                    self.mapping.update(f"contribution:{entry.path}", uncertainty=[f"reused source {meta['primary_source']} not found at the pinned commit"])
            return out

        for path in sorted(by_path):
            entry = by_path[path]
            self._contribution(entry, inv, keys[path], lineage(entry), added(path))
        for path, history in histories.items():
            self._review(path, history)

    def _home(self, entry: InventoryEntry) -> Problem:
        problem = self.problems.get(entry.problem_key or "")
        if problem is None:
            raise ImportError_(f"{entry.path}: no problem {entry.problem_key}")
        return problem

    def _contribution(self, entry: InventoryEntry, inv: Inventory, ids: dict[str, str], lineage: list[dict], first_added: str | None) -> None:
        home = self._home(entry)
        headers = entry.headers
        content = inv.contents[entry.blob]
        text = content.decode("utf-8")
        folder_key = f"{entry.path.split('/')[2]}/{entry.folder}"
        owner = self.owner()
        humans: list[dict] = []
        mode = "ai_only"
        third_party = None
        extension: dict[str, Any] = {"collection": entry.collection, "class": entry.cls, "source_path": entry.path, "source_blob": entry.blob,
                                     "folder": entry.folder, "version": entry.version}
        declared = {k: headers.values[k][0] for k in ("FIRST_POSTED", "ATTEMPT_STATUS", "ENTRY_KIND", "MODEL", "COMPLETION", "REVISION_OF",
                                                      "REVISION_VERSION", "REVISION_BASIS", "RESEARCH_GENERATED", "ATTEMPT_ORIGIN") if k in headers.values}
        if declared:
            extension["headers"] = declared
        status = headers.attempt_status
        claim: dict[str, Any] | None = None
        external_artifacts: list[dict] = []
        alias_name = home.alias
        if entry.cls == "external_claim_summary":
            openai = headers.data.get("OPENAI_CLAIM") or {}
            model_uses = [self._model_use(folder_key, None)]
            claim = {"type": "literature_report", "scope_statement": "Summary of a claim published in openai/math; not a claim by this platform.",
                     "assumptions": [], "limitations": ["The linked openai/math material has not been examined or verified by the platform."]}
            extension["openai"] = {k: openai.get(k) for k in ("source_commit", "release_date", "match", "resolution", "second_pass") if k in openai}
            extension["openai"]["families"] = [f.get("title") for f in openai.get("families", [])][:10]
            if re.fullmatch(r"[0-9a-f]{40}", str(openai.get("source_commit", ""))):
                external_artifacts.append({"role": "supplementary", "location": "external_pinned",
                                           "external": {"url": "https://github.com/openai/math", "pin": {"kind": "git_commit", "value": openai["source_commit"]}},
                                           "description": "openai/math at the pinned commit (Apache-2.0); linked, not hosted."})
            title = f"OpenAI claim summary for {alias_name}"
        elif entry.cls == "human_contribution":
            ident = entry.problem_key.split(":", 1)[1]
            override = self.overrides["human_contributions"][ident]
            humans = [self.person(login=a.get("login"), display_name=a["display_name"], roles=["investigation", "writing_original_draft"],
                                  confirmation="listed_by_submitter") for a in override["authors"]]
            mode = override["contribution_mode"]
            model_uses = [{"provider": m["provider"], "declared_name": m["declared_name"], "family": m.get("family"), "version": "unknown",
                           "role": m["role"], "settings": None, "generation_date": None,
                           "provenance": {"level": "declared", "evidence": [{"kind": "statement", "note": "disclosed in the contribution text"}]}}
                          for m in override["model_uses"]]
            claim = {"type": "literature_report", "scope_statement": "Summary written by the legacy site of an externally published contribution.",
                     "assumptions": [], "limitations": ["The underlying work is published by its authors and linked, not reproduced."]}
            authors = ", ".join(a["display_name"] for a in override["authors"])
            third_party = [{"description": f"Underlying work by {authors}", "source_url": s} for s in override["external_sources"]][:1]
            extension["external_sources"] = override["external_sources"]
            title = f"Human contribution summary on {alias_name}: {authors}"
        else:
            source_folder = folder_key
            if entry.cls == "reused_writeup":
                meta = headers.data["COLLECTION_METADATA"]
                source_folder = f"{entry.path.split('/')[2]}/{meta['source_model']}"
                extension["collection_metadata"] = {k: meta.get(k) for k in ("kind", "primary_source", "source_model", "source_claim")}
                if meta.get("source_completion") is not None:
                    extension["collection_metadata"]["source_completion"] = str(meta["source_completion"])
            model_uses = [self._model_use(source_folder, headers.first("MODEL"))]
            label = model_uses[0]["declared_name"]
            if entry.cls == "statement_copy":
                title = f"Statement copy in the {label} collection ({alias_name})"
            elif entry.cls == "reused_writeup":
                title = f"Reused writeup on {alias_name} ({label})"
            else:
                title = f"{label} attempt on {alias_name}" + (f", version {entry.version}" if entry.version and entry.version > 1 else "")
            if entry.cls != "statement_copy":
                if status:
                    claim = {"type": CLAIMS[status], "scope_statement": f"Legacy ATTEMPT_STATUS: {status}. Recorded as the author's claim, never as a problem status.",
                             "assumptions": [], "limitations": []}
                else:
                    extension["retired_inferred_status"] = legacy_prep.infer_attempt_status(text)
            completion = headers.first("COMPLETION") or (legacy_prep.extract_completion(text) if entry.cls == "attempt" else None)
            if completion is not None:
                extension["legacy_completion_estimate"] = str(completion)
        if entry.uncertainty:
            extension["uncertainty"] = list(entry.uncertainty)
            self.uncertain += 1
        taken: set[str] = set()
        filename = _safe_name(entry.path.rsplit("/", 1)[1], taken)
        artifacts = [{"role": "manuscript_source", "location": "in_repository", "path": f"files/{filename}", "media_type": "application/x-tex"}, *external_artifacts]
        record: dict[str, Any] = {
            "schema_version": 1,
            "contribution_id": ids["contribution_id"],
            "revision_id": ids["revision_id"],
            "expected_predecessor": None,
            "type": "legacy_record",
            "home_problem_id": home.problem_id,
            "targets": [{"target_kind": "problem", "problem_id": home.problem_id, "statement_revision_id": home.statement_revision_id, "scope": "whole_statement"}],
            "title": title,
            "profiles": [{"id": "mathematical_argument", "version": 1, "required": True}],
        }
        if claim:
            record["claim"] = claim
        record.update(
            attribution={"submitter": owner, "humans": humans, "organisations": [], "contribution_mode": mode},
            model_uses=model_uses,
            lineage=lineage,
            artifacts=artifacts,
            rights=self._rights(third_party),
            declarations=self._declarations(owner["person_ref"]),
            extensions={EXTENSION: extension},
        )
        dates = []
        if headers.first_posted:
            dates.append(("first_posted", DateClaim(headers.first_posted, "day"), "legacy_header", f"FIRST_POSTED: {headers.first_posted}"))
        if first_added:
            dates.append(("repository_first_added", DateClaim(first_added, "instant"), "git_author_date", "first added to the legacy repository"))
        self._register_contribution(f"contribution:{entry.path}", entry.path, entry.blob, home, record, {f"files/{filename}": content}, dates)
        self.counts[f"contributions_{entry.cls}"] += 1

    def _review(self, path: str, history: ReviewHistory) -> None:
        key = {"erdos": "erdos", "open_problems": "top", "mo": "mo"}[history.collection] + ":" + history.problem_id
        home = self.problems.get(key)
        if home is None:
            raise ImportError_(f"{path}: review for unknown problem {key}")
        ids = self.mapping.ids(f"review:{path}", contribution_id="contribution", revision_id="revision")
        owner = self.owner()
        current = history.current
        data = current.data if current else {}
        humans = []
        seen: set[str] = set()
        for login in sorted(set().union(*(v.logins() for v in history.versions))):
            if login not in seen:
                seen.add(login)
                humans.append(self.person(login=login, display_name=login, roles=["validation"], confirmation="listed_by_submitter"))
        issues = {}
        for number in sorted({v.issue_number for v in history.versions if v.issue_number}):
            snap = self.snapshot.get("issues", {}).get(str(number))
            issues[str(number)] = {
                "url": f"{LEGACY_URL}/issues/{number}",
                "author": snap["author"] if snap else "unknown",
                "labellers": sorted({x["actor"] for x in snap.get("labelled") or [] if x.get("actor")}) if snap else ["unknown"],
            }
        versions = [{"commit": v.commit, "author_date": v.author_date, "blob": v.blob, "state": "deleted" if v.data is None else "present", "data": v.data}
                    for v in history.versions]
        files = {"files/review-history.json": json.dumps({"path": path, "versions": versions}, indent=2, sort_keys=True, ensure_ascii=False).encode() + b"\n"}
        artifacts = [{"role": "data", "location": "in_repository", "path": "files/review-history.json", "media_type": "application/json",
                      "description": "Every historical state of the legacy review file, recovered from Git."}]
        label = (data or {}).get("label") or (data or {}).get("status")
        record = {
            "schema_version": 1,
            "contribution_id": ids["contribution_id"],
            "revision_id": ids["revision_id"],
            "expected_predecessor": None,
            "type": "legacy_record",
            "home_problem_id": home.problem_id,
            "targets": [{"target_kind": "problem", "problem_id": home.problem_id, "statement_revision_id": home.statement_revision_id, "scope": "whole_statement"}],
            "title": f"Legacy community review of {home.alias}" + (f" (label: {label})" if label else "") + (" [removed from the legacy site]" if history.deleted else ""),
            "profiles": [{"id": "mathematical_argument", "version": 1, "required": True}],
            "attribution": {"submitter": owner, "humans": humans, "organisations": [], "contribution_mode": "human_only" if humans else "ai_only"},
            "model_uses": [] if humans else [self._model_use("top_problems/openai", None)],
            "lineage": [],
            "artifacts": artifacts,
            "rights": self._rights(),
            "declarations": self._declarations(owner["person_ref"]),
            "extensions": {EXTENSION: {"collection": history.collection, "class": "review", "source_path": path, "raw_label": label,
                                       "note": (data or {}).get("note"), "citations": (data or {}).get("citations") or [],
                                       "issues": issues, "deleted": history.deleted,
                                       "roles": "humans are reviewers or submitters named in the legacy file; issue authors and labellers are listed per issue"}},
        }
        dates = []
        if current and (data or {}).get("reviewed_at") and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(data["reviewed_at"])):
            dates.append(("activity", DateClaim(data["reviewed_at"], "day"), "legacy_header", f"reviewed_at: {data['reviewed_at']}"))
        self._register_contribution(f"review:{path}", path, current.blob if current else None, home, record, files, dates)
        self.counts["contributions_review"] += 1

    def _register_contribution(self, key: str, path: str, blob: str | None, home: Problem, record: dict, files: dict[str, bytes],
                               dates: list[tuple[str, DateClaim, str, str]]) -> None:
        cid, rid = record["contribution_id"], record["revision_id"]
        alias = self._reserve(lambda s: plan_contribution_alias(self.policy, s, home_problem_alias=home.alias, contribution_type="legacy_record", entity_id=cid), cid)
        self._validate("contribution", record, path)
        manifest = manifest_from_blobs({p: (b, "100644") for p, b in files.items()}, record["artifacts"])
        fingerprint = scientific_fingerprint(record, manifest)
        previous = self.mapping.records.get(key, {}).get("scientific_fingerprint")
        if previous is not None and previous != fingerprint:
            raise ImportError_(
                f"{path}: content differs from the previously imported revision {rid}; "
                "a changed record needs a new revision, not an overwrite"
            )
        events = [self._event("contribution_submitted", [cid, rid],
                              {"contribution_id": cid, "revision_id": rid, "intake_ref": {"kind": "legacy_import", "repository": LEGACY_REPOSITORY, "path": path}},
                              {"contribution_id": cid, "revision_id": rid})]
        for kind, claim, source, text in dates:
            events.append(self._event("date_declared", [cid], {"subject_id": cid, "kind": kind, "claim": claim.to_json(), "source_text": text},
                                      {"subject_id": cid, "kind": kind}, occurred_at=claim, time_source=source))
        self._record_events(events)
        accept_revision(
            self.store, contribution_id=cid, revision_id=rid, expected_predecessor=None, scientific_fingerprint=fingerprint,
            authorization_binding=digest({"version": "K-legacy/1", "import": IMPORT_ID, "source": path, "blob": blob, "S": fingerprint}),
            ctx=self.ctx, cache=self.cache,
        )
        base = str(contribution_dir(home.problem_id, cid, "legacy_record"))
        self.files[f"research/{base}/contribution.yaml"] = strict_yaml.dump(record).encode("utf-8")
        for p, b in files.items():
            self.files[f"research/{base}/{p}"] = b
        self.mapping.update(key, kind="contribution", alias=alias, home_problem=home.alias, source=self._source(path, blob),
                            files={p: path.rsplit("/", 1)[1] for p in files}, scientific_fingerprint=fingerprint)

    # ------------------------------------------------------------------ run

    def run(self) -> ImportResult:
        inventory = build_inventory(self.repo)
        histories = review_history(self.repo)
        self.owner()
        self.build_problems(inventory)
        self.register_problems()
        self.build_contributions(inventory, histories)
        self.files[f"research/migration/{IMPORT_ID}/inventory.json"] = json.dumps(inventory.as_json(), indent=1, sort_keys=True).encode() + b"\n"
        self.files[f"research/migration/{IMPORT_ID}/inventory.md"] = inventory.report().encode()
        self.files[f"research/migration/{IMPORT_ID}/owner-declarations.yaml"] = (CONFIG / "owner-declarations.yaml").read_bytes()
        self.files[f"research/migration/{IMPORT_ID}/github-snapshot.json"] = json.dumps(self.snapshot, indent=2, sort_keys=True).encode() + b"\n"
        self.files[f"research/migration/{IMPORT_ID}/mapping.jsonl"] = self.mapping.dump()
        events = self.store.export_jsonl()
        self.files["ledger/events.jsonl"] = events
        for rel, content in sorted(self.files.items()):
            target = self.out / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists() or target.read_bytes() != content:
                target.write_bytes(content)
        return ImportResult(dict(sorted(self.counts.items())), len(self.files), events.count(b"\n"), self.store.head(), self.uncertain)


def main() -> None:
    parser = argparse.ArgumentParser(description="Idempotent legacy import")
    parser.add_argument("--legacy", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    result = LegacyImporter(LegacyRepo(args.legacy), args.out).run()
    print(json.dumps(result.__dict__, indent=2))


if __name__ == "__main__":
    main()
