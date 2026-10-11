"""Keep the JSON Schemas, the Python vocabularies and the identifier rules in step."""

import json
from collections.abc import Iterator

import pytest
from jsonschema import Draft202012Validator

from rp import PACKAGE_ROOT, vocab
from rp.identity.ids import KIND_PREFIXES, id_pattern
from rp.validation.records import FORMAT_CHECKER, RECORD_TYPES, SCHEMA_BASE, schema_registry

SCHEMAS = {
    entry.name: json.loads(entry.read_text(encoding="utf-8"))
    for entry in (PACKAGE_ROOT / "schemas").iterdir()
    if entry.name.endswith(".schema.json")
}
COMMON = SCHEMAS["common.schema.json"]["$defs"]
CONTRIBUTION = SCHEMAS["contribution.schema.json"]
PROBLEM = SCHEMAS["problem.schema.json"]
EVENT = SCHEMAS["event.schema.json"]


def walk(node, key=None) -> Iterator[tuple[str | None, object]]:
    yield key, node
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk(v, k)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item, key)


@pytest.mark.parametrize("name", sorted(SCHEMAS))
def test_schemas_are_valid_2020_12(name):
    schema = SCHEMAS[name]
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == SCHEMA_BASE + name
    Draft202012Validator.check_schema(schema)


def test_every_schema_is_a_record_type_or_common():
    assert set(SCHEMAS) == set(RECORD_TYPES.values()) | {"common.schema.json"}


def test_all_refs_resolve():
    registry = schema_registry()
    for name, schema in SCHEMAS.items():
        resolver = registry.resolver(base_uri=schema["$id"])
        for key, value in walk(schema):
            if key == "$ref":
                resolver.lookup(value)


def test_only_checked_formats_are_used():
    used = {value for schema in SCHEMAS.values() for key, value in walk(schema) if key == "format" and isinstance(value, str)}
    assert used <= set(FORMAT_CHECKER.checkers), used - set(FORMAT_CHECKER.checkers)


def test_closed_objects():
    """Every object schema with properties is closed, so unknown core fields are rejected."""
    for name, schema in SCHEMAS.items():
        for _, node in walk(schema):
            if isinstance(node, dict) and "properties" in node and node.get("type") == "object":
                assert node.get("additionalProperties") is False, f"{name}: open object with {sorted(node['properties'])}"


@pytest.mark.parametrize("kind", sorted(KIND_PREFIXES))
def test_identifier_patterns_match_python(kind):
    name = "person_id" if kind == "person" else f"{kind}_id"
    assert COMMON[name]["pattern"] == id_pattern(kind)


@pytest.mark.parametrize(
    "enum, expected",
    [
        (PROBLEM["properties"]["kind"]["enum"], vocab.PROBLEM_KINDS),
        (CONTRIBUTION["properties"]["type"]["enum"], vocab.CONTRIBUTION_TYPES),
        (CONTRIBUTION["$defs"]["claim"]["properties"]["type"]["enum"], vocab.CLAIM_TYPES),
        (CONTRIBUTION["$defs"]["target"]["oneOf"][0]["properties"]["scope"]["enum"], vocab.TARGET_SCOPES),
        (CONTRIBUTION["$defs"]["review"]["properties"]["finding"]["enum"], vocab.REVIEW_FINDINGS),
        (CONTRIBUTION["$defs"]["lineage"]["properties"]["relation"]["enum"], vocab.LINEAGE_RELATIONS),
        (CONTRIBUTION["$defs"]["artifact_declaration"]["properties"]["role"]["enum"], vocab.ARTIFACT_ROLES),
        (PROBLEM["$defs"]["relation"]["properties"]["type"]["enum"], vocab.RELATION_TYPES),
        (PROBLEM["$defs"]["derivation"]["properties"]["nature"]["enum"], vocab.DERIVED_NATURES),
        (PROBLEM["$defs"]["source_observation"]["properties"]["normalised_status"]["enum"], vocab.NORMALISED_SOURCE_STATUSES),
        (COMMON["attribution"]["properties"]["contribution_mode"]["enum"], vocab.CONTRIBUTION_MODES),
        (COMMON["provenance"]["properties"]["level"]["enum"], vocab.PROVENANCE_LEVELS),
        (COMMON["person"]["properties"]["roles"]["items"]["enum"], vocab.HUMAN_ROLES),
        (COMMON["person"]["properties"]["authorship_confirmation"]["enum"], vocab.AUTHORSHIP_CONFIRMATION),
        (COMMON["model_use"]["properties"]["role"]["enum"], vocab.MODEL_ROLES),
        (COMMON["declaration"]["properties"]["source"]["enum"], vocab.DECLARATION_SOURCES),
        (COMMON["pin"]["properties"]["kind"]["enum"], vocab.PIN_KINDS),
        (SCHEMAS["artifact-record.schema.json"]["properties"]["role"]["enum"], vocab.RECORD_ARTIFACT_ROLES),
        (SCHEMAS["artifact-record.schema.json"]["properties"]["availability"]["enum"], vocab.ARTIFACT_AVAILABILITY),
        (SCHEMAS["discipline.schema.json"]["properties"]["status"]["enum"], vocab.DISCIPLINE_STATUSES),
        (EVENT["properties"]["type"]["enum"], vocab.EVENT_TYPES),
        (EVENT["properties"]["time_source"]["enum"], vocab.TIME_SOURCES),
        (EVENT["properties"]["actor"]["properties"]["kind"]["enum"], vocab.ACTOR_KINDS),
        (EVENT["$defs"]["date_declared"]["properties"]["kind"]["enum"], vocab.DECLARED_DATE_KINDS),
    ],
)
def test_enums_match_vocab(enum, expected):
    assert tuple(enum) == tuple(expected)


def test_review_like_and_link_only_conditions_match_vocab():
    review_if = CONTRIBUTION["allOf"][0]["if"]["properties"]["type"]["enum"]
    claim_if = CONTRIBUTION["allOf"][1]["if"]["properties"]["type"]["enum"]
    link_only = CONTRIBUTION["$defs"]["artifact_declaration"]["allOf"][2]["if"]["properties"]["role"]["enum"]
    assert set(review_if) == vocab.REVIEW_LIKE_TYPES
    assert set(claim_if) == vocab.CLAIM_REQUIRED_TYPES
    assert set(link_only) == vocab.LINK_ONLY_ARTIFACT_ROLES


def test_every_event_type_has_a_payload_schema():
    conditioned = {branch["if"]["properties"]["type"]["const"] for branch in EVENT["allOf"]}
    assert conditioned == set(vocab.EVENT_TYPES)
    for event_type in vocab.EVENT_TYPES:
        payload = EVENT["$defs"][event_type]
        assert payload["additionalProperties"] is False
