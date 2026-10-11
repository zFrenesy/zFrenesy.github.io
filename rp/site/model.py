"""Site model: the research tree and ledger, loaded into page-ready objects."""

from __future__ import annotations

import json
import re
import stat
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rp import strict_yaml
from rp.canonical import sha256_digest
from rp.fingerprint import manifest_from_blobs, scientific_fingerprint
from rp.identity.ids import parse_id
from rp.identity.paths import contribution_dir, problem_dir
from rp.ledger.state import LedgerCorruption, LedgerState, rebuild
from rp.validation.records import validate_record

__all__ = ["Contribution", "Problem", "SiteModel", "load_model", "slugify"]

EXT = "org.we-solve.legacy"
SOURCES = {
    "erdos": ("erdos", "Erdős problems"),
    "top": ("top-open-problems", "Top Open Problems"),
    "mo": ("mathoverflow", "MathOverflow"),
    "economics": ("economics-catalogue", "Economics catalogue"),
}
CLAIM_LABELS = {
    "full_solution": "Full solution claimed",
    "full_disproof": "Full disproof claimed",
    "partial_result": "Partial result",
    "conditional_result": "Conditional result",
    "computational_evidence": "Computational evidence",
    "literature_report": "Literature report",
    "exploration": "Exploration",
}


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "unknown"


@dataclass
class Contribution:
    record: dict[str, Any]
    alias: str
    folder: Path
    files: dict[str, bytes]
    revision_label: str
    accepted_fingerprint: str
    dates: dict[str, dict[str, Any]] = field(default_factory=dict)
    accepted_at: str | None = None
    problem: Problem | None = None
    rendered: Any = None

    @property
    def id(self) -> str:
        return self.record["contribution_id"]

    @property
    def hex(self) -> str:
        return parse_id(self.id).hex

    @property
    def legacy(self) -> dict[str, Any]:
        return self.record.get("extensions", {}).get(EXT, {})

    @property
    def cls(self) -> str:
        return self.legacy.get("class", self.record["type"])

    @property
    def is_review(self) -> bool:
        return self.cls in {"review", "author_response"}

    @property
    def claim_type(self) -> str | None:
        claim = self.record.get("claim")
        return claim["type"] if claim else None

    @property
    def claim_label(self) -> str:
        return CLAIM_LABELS.get(self.claim_type or "", "No claim recorded")

    @property
    def mode(self) -> str:
        return self.record["attribution"]["contribution_mode"]

    @property
    def model_names(self) -> list[str]:
        return [m["declared_name"] for m in self.record["model_uses"]]

    @property
    def sort_date(self) -> str:
        for key in ("first_posted", "repository_first_added", "activity"):
            if key in self.dates:
                return self.dates[key]["value"][:10]
        return ""

    @property
    def url(self) -> str:
        return f"/contributions/{self.alias}/"

    @property
    def revision_url(self) -> str:
        return f"/contributions/{self.alias}/{self.revision_label}/"


@dataclass
class Problem:
    record: dict[str, Any]
    alias: str
    folder: Path
    statement_name: str
    statement: bytes
    contributions: list[Contribution] = field(default_factory=list)
    rendered: Any = None

    @property
    def id(self) -> str:
        return self.record["problem_id"]

    @property
    def hex(self) -> str:
        return parse_id(self.id).hex

    @property
    def legacy(self) -> dict[str, Any]:
        return self.record.get("extensions", {}).get(EXT, {})

    @property
    def collection(self) -> str:
        return self.legacy.get("collection", "")

    @property
    def source(self) -> tuple[str, str]:
        return SOURCES.get(self.collection, ("other", "Other"))

    @property
    def primary_discipline(self) -> str:
        return next(d["discipline"] for d in self.record["disciplines"] if d["role"] == "primary")

    @property
    def disciplines(self) -> list[str]:
        return [d["discipline"] for d in self.record["disciplines"]]

    @property
    def source_status(self) -> dict[str, Any] | None:
        return self.record["sources"][0] if self.record["sources"] else None

    @property
    def url(self) -> str:
        return f"/problems/{self.alias}/"

    @property
    def attempts(self) -> list[Contribution]:
        return [c for c in self.contributions if not c.is_review]

    @property
    def reviews(self) -> list[Contribution]:
        return [c for c in self.contributions if c.is_review]

    @property
    def last_activity(self) -> str:
        return max((c.sort_date for c in self.contributions), default="")

    def number_key(self) -> tuple:
        ident = self.record["external_ids"][0]["identifier"] if self.record["external_ids"] else self.alias
        parts = re.split(r"(\d+)", ident)
        return (self.collection, *[(1, int(p)) if p.isdigit() else (0, p) for p in parts])


@dataclass
class SiteModel:
    problems: dict[str, Problem]
    contributions: dict[str, Contribution]
    people: dict[str, dict[str, Any]]
    events: list[dict[str, Any]]

    def by_alias(self) -> dict[str, Problem | Contribution]:
        found: dict[str, Problem | Contribution] = {p.alias: p for p in self.problems.values()}
        found.update({c.alias: c for c in self.contributions.values()})
        return found


def load_model(work: Path) -> SiteModel:
    work = Path(work).resolve()
    research = work / "research"
    events = [json.loads(line, object_pairs_hook=_json_object)
              for line in _read_inside(work, "ledger/events.jsonl").decode("utf-8").splitlines()]
    event_ids, event_keys = set(), set()
    for event in events:
        _validate("event", event)
        if event["event_id"] in event_ids or event["idempotency_key"] in event_keys:
            raise ValueError("duplicate event ID or idempotency key in publication ledger")
        event_ids.add(event["event_id"])
        event_keys.add(event["idempotency_key"])
    try:
        state = rebuild(events)
    except LedgerCorruption as exc:
        raise ValueError(f"invalid publication ledger: {exc}") from exc
    dates: dict[str, dict[str, dict]] = defaultdict(dict)
    accepted: dict[str, dict] = {}
    statements: dict[str, dict] = {}
    for e in events:
        if e["type"] == "date_declared":
            dates[e["payload"]["subject_id"]][e["payload"]["kind"]] = e["payload"]["claim"]
        elif e["type"] == "revision_accepted":
            accepted[e["payload"]["revision_id"]] = e
        elif e["type"] == "statement_revised":
            sid = e["payload"]["statement_revision_id"]
            if sid in statements:
                raise ValueError(f"duplicate statement revision in publication ledger: {sid}")
            statements[sid] = e
    problems: dict[str, Problem] = {}
    contributions: dict[str, Contribution] = {}
    people: dict[str, dict[str, Any]] = {}
    for problem_yaml in sorted(research.glob("problems/*/*/problem.yaml")):
        folder = problem_yaml.parent
        record = strict_yaml.load(_read_inside(research, problem_yaml.relative_to(research).as_posix()))
        _validate("problem", record)
        pid, sid = record["problem_id"], record["statement_revision_id"]
        if pid in problems:
            raise ValueError(f"duplicate problem record: {pid}")
        if folder.relative_to(research).as_posix() != str(problem_dir(pid)):
            raise ValueError(f"problem source path does not match its identity: {pid}")
        name = record["statement_artifact"]["path"]
        alias = _bound_alias(state, pid)
        statement = _read_inside(folder, name)
        event = statements.get(sid)
        if (state.statement_heads.get(pid) != sid or event is None or event["payload"]["problem_id"] != pid
                or event["payload"]["predecessor"] != record["expected_statement_predecessor"]):
            raise ValueError(f"problem source does not match its accepted statement revision: {pid}")
        descriptor = json.loads(_read_inside(work, f"ledger/statement-revisions/{sid}.json"), object_pairs_hook=_json_object)
        _validate("statement_revision", descriptor)
        if (descriptor["problem_id"] != pid or descriptor["statement_revision_id"] != sid
                or descriptor["predecessor"] != record["expected_statement_predecessor"]
                or descriptor["recorded_at"] != event["recorded_at"]
                or descriptor["statement_artifact"] != {"path": name, "digest": sha256_digest(statement), "bytes": len(statement)}):
            raise ValueError(f"statement source differs from its accepted descriptor: {sid}")
        problem = Problem(record, alias, folder, name, statement)
        problems[problem.id] = problem
        for contribution_yaml in sorted([*folder.glob("contributions/*/contribution.yaml"), *folder.glob("reviews/*/contribution.yaml")]):
            cfolder = contribution_yaml.parent
            crecord = strict_yaml.load(_read_inside(research, contribution_yaml.relative_to(research).as_posix()))
            _validate("contribution", crecord)
            cid, rid = crecord["contribution_id"], crecord["revision_id"]
            if cid in contributions:
                raise ValueError(f"duplicate contribution record: {cid}")
            if (crecord["home_problem_id"] != pid
                    or cfolder.relative_to(research).as_posix() != str(contribution_dir(pid, cid, crecord["type"]))):
                raise ValueError(f"contribution source path does not match its home problem and identity: {cid}")
            calias = _bound_alias(state, cid)
            event = accepted.get(rid)
            if (event is None or event["payload"]["contribution_id"] != cid
                    or state.revision_heads.get(cid) != rid
                    or event["payload"]["predecessor"] != crecord["expected_predecessor"]):
                raise ValueError(f"contribution source does not match its accepted revision: {cid}")
            revision_label = event["payload"]["sequence_label"]
            files, manifest = _contribution_files(cfolder, crecord["artifacts"])
            accepted_fingerprint = event["payload"]["scientific_fingerprint"]
            if scientific_fingerprint(crecord, manifest) != accepted_fingerprint:
                raise ValueError(f"contribution source differs from its accepted scientific fingerprint: {cid} {revision_label}")
            contribution = Contribution(
                crecord, calias, cfolder, files, revision_label, accepted_fingerprint,
                dates.get(cid, {}), event["recorded_at"], problem,
            )
            problem.contributions.append(contribution)
            contributions[contribution.id] = contribution
            for person in [crecord["attribution"]["submitter"], *crecord["attribution"]["humans"]]:
                key = parse_id(person['person_ref']).hex
                entry = people.setdefault(key, {"key": key, "display_name": person["display_name"], "login": person["login_at_event"],
                                                "person_ref": person["person_ref"], "github_id": person["github_id"], "submitted": [], "contributed": []})
                (entry["submitted"] if person is crecord["attribution"]["submitter"] else entry["contributed"]).append(contribution)
        problem.contributions.sort(key=lambda c: (c.is_review, c.sort_date or "9999", c.alias))
    if missing := set(state.statement_heads) - set(problems):
        raise ValueError(f"accepted problem source is missing: {sorted(missing)[0]}")
    if missing := set(state.revision_heads) - set(contributions):
        raise ValueError(f"accepted contribution source is missing: {sorted(missing)[0]}")
    return SiteModel(problems, contributions, people, events)


def _validate(kind: str, record: dict) -> None:
    issues = [i for i in validate_record(kind, record, catalog=None) if i.severity == "error"]
    if issues:
        raise ValueError(f"invalid {kind} input: " + "; ".join(map(str, issues)))


def _read_inside(folder: Path, name: str) -> bytes:
    path = folder / name
    if Path(name).is_absolute() or ".." in Path(name).parts or not path.resolve().is_relative_to(folder.resolve()):
        raise ValueError(f"artifact escapes its document: {name}")
    current = path
    while True:
        if current.is_symlink():
            raise ValueError(f"symlink artifact is not supported: {name}")
        if current == folder:
            break
        current = current.parent
    if not path.exists():
        raise ValueError(f"missing publication source: {name}")
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError(f"publication source is not a regular file: {name}")
    return path.read_bytes()


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for key, value in pairs:
        if key in data:
            raise ValueError(f"duplicate JSON field in publication input: {key}")
        data[key] = value
    return data


def _bound_alias(state: LedgerState, entity_id: str) -> str:
    alias = state.live_alias_of(entity_id)
    if alias is None or state.aliases[alias].state != "bound":
        raise ValueError(f"{entity_id} has no bound alias in the ledger")
    return alias


def _contribution_files(folder: Path, artifacts: list[dict]) -> tuple[dict[str, bytes], list[dict]]:
    blobs = {}
    files_root = folder / "files"
    if files_root.is_symlink():
        raise ValueError("symlink artifact is not supported: files/")
    if files_root.exists() and not files_root.is_dir():
        raise ValueError("artifact files/ must be a directory")
    for path in sorted(files_root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"symlink artifact is not supported: {path.relative_to(folder)}")
        if path.is_dir() or path.name == ".DS_Store":
            continue
        name = path.relative_to(folder).as_posix()
        contents = _read_inside(folder, name)
        mode = "100755" if path.stat().st_mode & 0o111 else "100644"
        blobs[name] = (contents, mode)
    manifest = manifest_from_blobs(blobs, artifacts)
    return {name: contents for name, (contents, _) in blobs.items()}, manifest
