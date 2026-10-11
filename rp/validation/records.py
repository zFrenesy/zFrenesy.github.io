"""Validate platform records against their schemas and semantic rules.

Every problem is reported as an ``Issue`` with a stable ``code`` (for tests,
fixtures and contributor-facing messages) and a JSON Pointer. Schema errors
come first; semantic checks run only on schema-valid data, so they can rely
on its shape. Validation never fetches anything: schemas resolve from the
package, and unknown ``$ref``s or formats are errors, not silent passes.
"""

from __future__ import annotations

import functools
import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import best_match
from referencing import Registry
from referencing.jsonschema import DRAFT202012

from rp import PACKAGE_ROOT, strict_yaml
from rp.canonical import canonical_json
from rp.fingerprint import manifest_sort_key
from rp.identity.relations import check_relations, relations_from_problem
from rp.strict_yaml import StrictYamlError
from rp.timeutil import is_calendar_date, is_instant
from rp.vocab import (
    CLAIM_REQUIRED_TYPES,
    OPEN_DISCIPLINE_STATUSES,
    REVIEW_LIKE_TYPES,
    REVISION_TARGETED_TYPES,
)

if TYPE_CHECKING:
    from rp.catalog import Catalog

__all__ = [
    "FORMAT_CHECKER",
    "RECORD_TYPES",
    "Issue",
    "RecordLoadError",
    "infer_record_type",
    "load_record",
    "publication_issues",
    "schema_registry",
    "validate_file",
    "validate_record",
]

SCHEMA_BASE = "https://we-solve.github.io/schemas/v1/"
RECORD_TYPES = {
    "problem": "problem.schema.json",
    "statement_revision": "statement-revision.schema.json",
    "contribution": "contribution.schema.json",
    "artifact_record": "artifact-record.schema.json",
    "revision_descriptor": "revision-descriptor.schema.json",
    "event": "event.schema.json",
    "publication_snapshot": "publication-snapshot.schema.json",
    "discipline": "discipline.schema.json",
    "profile": "profile.schema.json",
    "alias_namespaces": "alias-namespaces.schema.json",
    "platform": "platform.schema.json",
    "classification": "classification.schema.json",
    "external_hosts": "external-hosts.schema.json",
}
FILENAME_TYPES = {"problem.yaml": "problem", "contribution.yaml": "contribution"}
MAX_MESSAGE = 300

# C0 controls other than tab, newline and carriage return; DEL; C1 controls.
_CONTROL = re.compile("[" + "".join(map(chr, [*range(0x00, 0x09), 0x0B, 0x0C, *range(0x0E, 0x20), *range(0x7F, 0xA0)])) + "]")
# Bidirectional embedding, override and isolate controls ("Trojan Source").
_BIDI = re.compile("[" + "".join(map(chr, [*range(0x202A, 0x202F), *range(0x2066, 0x206A)])) + "]")


@dataclass(frozen=True, slots=True)
class Issue:
    code: str
    message: str
    pointer: str = ""
    severity: str = "error"

    def __str__(self) -> str:
        where = f" at {self.pointer}" if self.pointer else ""
        return f"{self.severity}: {self.code}{where}: {self.message}"


class RecordLoadError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


# ---------------------------------------------------------------------------
# Formats. Only these are allowed; tests check every schema uses no others.

FORMAT_CHECKER = FormatChecker(formats=())


@FORMAT_CHECKER.checks("date")
def _check_date(value: object) -> bool:
    return not isinstance(value, str) or is_calendar_date(value)


@FORMAT_CHECKER.checks("date-time")
def _check_date_time(value: object) -> bool:
    return not isinstance(value, str) or is_instant(value)


@FORMAT_CHECKER.checks("uri")
def _check_uri(value: object) -> bool:
    if not isinstance(value, str):
        return True
    if any(c.isspace() for c in value) or _CONTROL.search(value) or not value.isascii():
        return False
    try:
        parts = urlsplit(value)
        parts.port  # noqa: B018 - raises on an invalid port
    except ValueError:
        return False
    return parts.scheme in ("https", "http") and bool(parts.hostname) and "@" not in parts.netloc


@FORMAT_CHECKER.checks("regex", raises=re.error)
def _check_regex(value: object) -> bool:
    if isinstance(value, str):
        re.compile(value)
    return True


# ---------------------------------------------------------------------------
# Schemas


@functools.cache
def schema_registry() -> Registry:
    resources = []
    for entry in sorted((PACKAGE_ROOT / "schemas").iterdir(), key=lambda e: e.name):
        if entry.name.endswith(".schema.json"):
            schema = json.loads(entry.read_text(encoding="utf-8"))
            resources.append((schema["$id"], DRAFT202012.create_resource(schema)))
    return Registry().with_resources(resources)


@functools.cache
def _validator(record_type: str) -> Draft202012Validator:
    if record_type not in RECORD_TYPES:
        raise ValueError(f"unknown record type {record_type!r}")
    schema = schema_registry().contents(SCHEMA_BASE + RECORD_TYPES[record_type])
    return Draft202012Validator(schema, registry=schema_registry(), format_checker=FORMAT_CHECKER)


def _pointer(path: Any) -> str:
    return "".join(f"/{str(p).replace('~', '~0').replace('/', '~1')}" for p in path)


def _shorten(message: str) -> str:
    return message if len(message) <= MAX_MESSAGE else message[: MAX_MESSAGE - 1] + "…"


def _schema_issues(record_type: str, data: Any) -> list[Issue]:
    issues = []
    for error in _validator(record_type).iter_errors(data):
        specific = best_match(error.context) if error.context else error
        issues.append(Issue(f"schema.{specific.validator}", _shorten(specific.message), _pointer(specific.absolute_path)))
    return sorted(set(issues), key=lambda i: (i.pointer, i.code, i.message))


# ---------------------------------------------------------------------------
# Semantic checks


def _strings(value: Any, pointer: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield pointer, value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield from _strings(item, f"{pointer}/{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _strings(item, f"{pointer}/{index}")


def _text_issues(data: Any) -> list[Issue]:
    issues = []
    for pointer, text in _strings(data):
        if _CONTROL.search(text):
            issues.append(Issue("text.control_character", "text contains a control character", pointer))
        if _BIDI.search(text):
            issues.append(Issue("text.bidi_control", "text contains a bidirectional override or isolate", pointer))
    return issues


def _attribution_issues(attribution: Mapping, model_uses: list, pointer: str) -> list[Issue]:
    issues = []
    mode = attribution["contribution_mode"]
    humans = attribution["humans"]
    if mode == "human_only" and model_uses:
        issues.append(Issue("attribution.mode_mismatch", "human_only work cannot list model uses", f"{pointer}/contribution_mode"))
    if mode in ("ai_only", "human_ai") and not model_uses:
        issues.append(
            Issue(
                "attribution.mode_mismatch",
                f"{mode} work must list at least one model use (the version may be 'unknown')",
                f"{pointer}/contribution_mode",
            )
        )
    if mode in ("human_only", "human_ai") and not humans:
        issues.append(Issue("attribution.mode_mismatch", f"{mode} work must list its human contributors", f"{pointer}/humans"))
    if mode == "ai_only":
        for index, person in enumerate(humans):
            if set(person["roles"]) - {"prompting", "submission"}:
                issues.append(
                    Issue(
                        "attribution.mode_mismatch",
                        "ai_only work can list humans only for prompting or submission; use human_ai",
                        f"{pointer}/humans/{index}/roles",
                    )
                )
    if attribution["submitter"]["authorship_confirmation"] != "confirmed":
        issues.append(
            Issue("attribution.submitter_unconfirmed", "the submitter is the authenticated actor and is always confirmed", f"{pointer}/submitter")
        )
    seen: set[str] = set()
    for index, person in enumerate(humans):
        if person["person_ref"] in seen:
            issues.append(Issue("attribution.duplicate_person", "person listed twice", f"{pointer}/humans/{index}"))
        seen.add(person["person_ref"])
    return issues


def _problem_issues(problem: Mapping, catalog: Catalog | None) -> list[Issue]:
    issues = []
    if problem["expected_statement_predecessor"] == problem["statement_revision_id"]:
        issues.append(Issue("problem.predecessor_self", "a statement revision cannot be its own predecessor", "/expected_statement_predecessor"))
    for rel_issue in check_relations(relations_from_problem(problem)):
        issues.append(Issue(rel_issue.code, rel_issue.message, "/relations"))
    if problem["kind"] == "derived":
        parent = problem["derivation"]["parent_problem_id"]
        linked = any(
            rel["target_problem_id"] == parent
            and (rel["type"] == "variant_of" or (rel["type"] == "subproblem_of" and rel.get("primary")))
            for rel in problem["relations"]
        )
        if not linked:
            issues.append(
                Issue(
                    "problem.derivation_parent",
                    "a derived problem needs a primary subproblem_of or a variant_of relation to its parent",
                    "/derivation/parent_problem_id",
                )
            )
    seen_ext: set[tuple[str, str]] = set()
    for index, ext in enumerate(problem["external_ids"]):
        key = (ext["scheme"], ext["identifier"])
        if key in seen_ext:
            issues.append(Issue("problem.duplicate_external_id", "external identifier listed twice", f"/external_ids/{index}"))
        seen_ext.add(key)
    if "attribution" in problem:
        issues.extend(_attribution_issues(problem["attribution"], problem.get("model_uses", []), "/attribution"))
    if catalog is not None:
        issues.extend(_problem_catalog_issues(problem, catalog))
    return issues


def _problem_catalog_issues(problem: Mapping, catalog: Catalog) -> list[Issue]:
    issues = []
    schemes = set()
    for index, entry in enumerate(problem["disciplines"]):
        pointer = f"/disciplines/{index}/discipline"
        config = catalog.disciplines.get(entry["discipline"])
        if config is None:
            issues.append(Issue("problem.unknown_discipline", f"unknown discipline {entry['discipline']!r}", pointer))
            continue
        open_ = config["status"] in OPEN_DISCIPLINE_STATUSES
        if entry["role"] == "primary" and not open_:
            issues.append(Issue("problem.discipline_not_open", f"{config['name']} is {config['status']}; submissions go on hold", pointer))
        if entry["role"] == "secondary" and not (open_ or config["usable_as_secondary"]):
            issues.append(Issue("problem.discipline_not_open", f"{config['name']} cannot be a secondary label yet", pointer))
        if config["classification"]:
            schemes.add(config["classification"]["scheme"])
    for index, cls in enumerate(problem["classifications"]):
        pointer = f"/classifications/{index}"
        if cls["scheme"] not in schemes:
            issues.append(
                Issue("problem.classification_scheme", f"scheme {cls['scheme']!r} does not belong to the problem's disciplines", pointer)
            )
            continue
        problem_text = catalog.classification_problem(cls["scheme"], cls["code"])
        if problem_text:
            issues.append(Issue("problem.classification_code", problem_text, pointer))
    return issues


def _contribution_issues(contribution: Mapping, catalog: Catalog | None) -> list[Issue]:
    issues = []
    ctype = contribution["type"]
    targets = contribution["targets"]
    problem_targets = [t for t in targets if t["target_kind"] == "problem"]
    revision_targets = [t for t in targets if t["target_kind"] == "contribution_revision"]
    if ctype in REVIEW_LIKE_TYPES:
        if len(revision_targets) != 1 or problem_targets:
            issues.append(Issue("contribution.review_target", f"a {ctype} targets exactly one contribution revision", "/targets"))
    elif ctype in REVISION_TARGETED_TYPES:
        if not revision_targets:
            issues.append(Issue("contribution.revision_target_required", f"a {ctype} targets the exact revision it addresses", "/targets"))
    elif revision_targets or not problem_targets:
        issues.append(Issue("contribution.problem_target_required", f"an {ctype} targets problems, not contribution revisions", "/targets"))
    if problem_targets and contribution["home_problem_id"] not in {t["problem_id"] for t in problem_targets}:
        issues.append(Issue("contribution.home_not_targeted", "the home problem must be one of the targets", "/home_problem_id"))
    seen_targets: set[bytes] = set()
    for index, target in enumerate(targets):
        key = canonical_json({k: v for k, v in target.items() if k in ("target_kind", "problem_id", "contribution_id", "revision_id")})
        if key in seen_targets:
            issues.append(Issue("contribution.duplicate_target", "target listed twice", f"/targets/{index}"))
        seen_targets.add(key)
        if target.get("contribution_id") == contribution["contribution_id"]:
            issues.append(Issue("contribution.self_target", "a contribution cannot target itself", f"/targets/{index}"))
    if contribution["expected_predecessor"] == contribution["revision_id"]:
        issues.append(Issue("contribution.predecessor_self", "a revision cannot be its own predecessor", "/expected_predecessor"))
    for index, item in enumerate(contribution["lineage"]):
        if item["contribution_id"] == contribution["contribution_id"]:
            issues.append(Issue("contribution.lineage_self", "lineage cannot point at the same contribution", f"/lineage/{index}"))
    issues.extend(_attribution_issues(contribution["attribution"], contribution["model_uses"], "/attribution"))
    submitter = contribution["attribution"]["submitter"]["person_ref"]
    for key in ("rights", "public_disclosure", "ai_disclosure"):
        if contribution["declarations"][key]["actor"] != submitter:
            issues.append(Issue("contribution.declaration_actor", "declarations are made by the submitter", f"/declarations/{key}/actor"))
    paths: set[str] = set()
    artifact_ids: set[str] = set()
    for index, artifact in enumerate(contribution["artifacts"]):
        if "path" in artifact:
            if artifact["path"] in paths:
                issues.append(Issue("contribution.duplicate_artifact", "artifact path listed twice", f"/artifacts/{index}/path"))
            paths.add(artifact["path"])
        if "artifact_id" in artifact:
            if artifact["artifact_id"] in artifact_ids:
                issues.append(Issue("contribution.duplicate_artifact", "artifact id listed twice", f"/artifacts/{index}/artifact_id"))
            artifact_ids.add(artifact["artifact_id"])
    seen_profiles: set[str] = set()
    for index, profile in enumerate(contribution["profiles"]):
        pointer = f"/profiles/{index}"
        if profile["id"] in seen_profiles:
            issues.append(Issue("contribution.duplicate_profile", "profile listed twice", pointer))
        seen_profiles.add(profile["id"])
        if catalog is None:
            continue
        known = catalog.profiles.get((profile["id"], profile["version"]))
        severity = "error" if profile["required"] else "warning"
        if known is None:
            code = "compatibility.unsupported_required_profile" if profile["required"] else "compatibility.unknown_optional_profile"
            issues.append(Issue(code, f"profile {profile['id']} v{profile['version']} is not supported here", pointer, severity))
        elif ctype not in known["applies_to"]:
            issues.append(Issue("contribution.profile_type_mismatch", f"profile {profile['id']} does not apply to {ctype}", pointer, severity))
    return issues


def _event_issues(event: Mapping) -> list[Issue]:
    issues = []
    payload = event["payload"]
    for key in ("entity_id", "subject_id", "problem_id", "contribution_id", "snapshot_id"):
        if key in payload and payload[key] not in event["targets"]:
            issues.append(Issue("event.target_mismatch", f"payload {key} must be one of the event targets", f"/payload/{key}"))
    if event["time_source"] in ("system_clock", "github_api", "git_committer_date", "git_author_date"):
        if event["occurred_at"]["precision"] != "instant":
            issues.append(Issue("event.precision_mismatch", f"{event['time_source']} times are instants", "/occurred_at"))
    if event["type"] == "date_declared" and event["time_source"] not in ("contributor_declaration", "legacy_header", "git_author_date"):
        issues.append(Issue("event.time_source", "declared dates come from a declaration, a legacy header or a Git author date", "/time_source"))
    if event["type"] == "date_declared" and payload["claim"] != event["occurred_at"]:
        issues.append(Issue("event.claim_mismatch", "occurred_at must equal the declared claim", "/occurred_at"))
    return issues


def _descriptor_issues(descriptor: Mapping) -> list[Issue]:
    issues = []
    first = descriptor["predecessor"] is None
    if first != (descriptor["sequence_label"] == "r1"):
        issues.append(Issue("descriptor.sequence_label", "r1 is exactly the revision without a predecessor", "/sequence_label"))
    manifest = descriptor["artifact_manifest"]
    keys = [canonical_json(entry) for entry in manifest]
    if len(set(keys)) != len(keys) or manifest != sorted(manifest, key=manifest_sort_key):
        issues.append(Issue("descriptor.manifest_order", "artifact manifest must be sorted and free of duplicates", "/artifact_manifest"))
    return issues


def _artifact_record_issues(record: Mapping) -> list[Issue]:
    stored = any(loc["kind"] in ("in_repository", "release_asset") for loc in record["locations"])
    if stored and (record["digest"] is None or record["bytes"] is None):
        return [Issue("artifact.digest_required", "stored artifacts record their digest and size", "/digest")]
    return []


def _snapshot_issues(snapshot: Mapping) -> list[Issue]:
    issues = []
    selected = snapshot["selected"]
    for key, field in (("contribution_revisions", "contribution_id"), ("statement_revisions", "problem_id")):
        ids = [item[field] for item in selected[key]]
        if len(ids) != len(set(ids)):
            issues.append(Issue("snapshot.duplicate_selection", f"each {field} is selected at most once", f"/selected/{key}"))
    return issues


def _semantic_issues(record_type: str, data: Any, catalog: Catalog | None) -> list[Issue]:
    issues = _text_issues(data)
    if record_type == "problem":
        issues += _problem_issues(data, catalog)
    elif record_type == "contribution":
        issues += _contribution_issues(data, catalog)
    elif record_type == "event":
        issues += _event_issues(data)
    elif record_type == "revision_descriptor":
        issues += _descriptor_issues(data)
    elif record_type == "artifact_record":
        issues += _artifact_record_issues(data)
    elif record_type == "publication_snapshot":
        issues += _snapshot_issues(data)
    elif record_type == "statement_revision" and data["predecessor"] == data["statement_revision_id"]:
        issues.append(Issue("statement.predecessor_self", "a statement revision cannot be its own predecessor", "/predecessor"))
    return issues


def validate_record(record_type: str, data: Any, *, catalog: Catalog | None) -> list[Issue]:
    """Return every issue found; an empty list (or warnings only) means the record is valid.

    ``catalog`` supplies disciplines, classifications and profiles. Pass ``None`` only for
    configuration records, which are what the catalog is built from.
    """
    issues = _schema_issues(record_type, data)
    if issues:
        return issues
    return _semantic_issues(record_type, data, catalog)


def publication_issues(contribution: Mapping) -> list[Issue]:
    """Requirements that must hold before a schema-valid contribution can be published (§16.2)."""
    issues = []
    for key in ("rights", "public_disclosure", "ai_disclosure"):
        if not contribution["declarations"][key]["confirmed"]:
            issues.append(Issue("publication.declaration_unconfirmed", f"the {key} declaration is not confirmed", f"/declarations/{key}"))
    for index, person in enumerate(contribution["attribution"]["humans"]):
        if person["authorship_confirmation"] == "declined":
            issues.append(Issue("publication.authorship_declined", "a listed person declined authorship", f"/attribution/humans/{index}"))
    if contribution["type"] in CLAIM_REQUIRED_TYPES and "claim" not in contribution:
        issues.append(Issue("publication.claim_missing", "claim type and scope are required", "/claim"))
    return issues


# ---------------------------------------------------------------------------
# Files


def _load_json_strict(data: bytes) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise RecordLoadError("json.duplicate_key", f"duplicate key {key!r}")
            result[key] = value
        return result

    def no_float(text: str) -> Any:
        raise RecordLoadError("json.float", f"{text} is a float; encode decimals as strings")

    def no_constant(text: str) -> Any:
        raise RecordLoadError("json.float", f"{text} is not allowed")

    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_float=no_float, parse_constant=no_constant)
    except UnicodeDecodeError as exc:
        raise RecordLoadError("json.encoding", "document is not valid UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise RecordLoadError("json.syntax", f"{exc.msg} (line {exc.lineno}, column {exc.colno})") from exc


def load_record(path: str | Path) -> Any:
    path = Path(path)
    data = path.read_bytes()
    if path.suffix in (".yaml", ".yml"):
        return strict_yaml.load(data)
    if path.suffix == ".json":
        return _load_json_strict(data)
    raise RecordLoadError("file.unsupported", f"{path.name}: expected .yaml, .yml or .json")


def infer_record_type(path: str | Path) -> str:
    path = Path(path)
    if path.name in FILENAME_TYPES:
        return FILENAME_TYPES[path.name]
    for parent in path.parents:
        candidate = parent.name.replace("-", "_")
        if candidate in RECORD_TYPES:
            return candidate
    raise RecordLoadError("file.unknown_type", f"cannot infer the record type of {path}; pass --type")


def validate_file(path: str | Path, *, record_type: str | None = None, catalog: Catalog | None) -> list[Issue]:
    try:
        record_type = record_type or infer_record_type(path)
        data = load_record(path)
    except StrictYamlError as exc:
        where = f"line {exc.line}" if exc.line else ""
        return [Issue(exc.code, str(exc), where)]
    except RecordLoadError as exc:
        return [Issue(exc.code, str(exc))]
    return validate_record(record_type, data, catalog=catalog)
