"""Controlled vocabularies shared by schemas, identity rules and validation.

The JSON Schemas repeat these enumerations; ``tests/unit/test_schema_vocab.py``
keeps the two in step. Rationale for the values: docs/adr/0007.
"""

PROBLEM_KINDS = ("catalogued", "literature", "proposed", "derived", "legacy_unclassified")
# Default catalogue views and open-problem counts (§15).
CATALOGUE_VIEW_KINDS = frozenset({"catalogued", "literature"})
CONTRIBUTOR_PROPOSED_KINDS = frozenset({"literature", "proposed", "derived"})

CONTRIBUTION_TYPES = (
    "attempt",
    "counterexample",
    "correction",
    "review",
    "author_response",
    "replication",
    "legacy_record",
)
REVIEW_LIKE_TYPES = frozenset({"review", "author_response"})
CLAIM_REQUIRED_TYPES = frozenset({"attempt", "counterexample"})
# Types whose targets are an exact contribution revision rather than a problem.
REVISION_TARGETED_TYPES = frozenset({"review", "author_response", "correction", "replication"})

# Alias letter for contribution aliases such as ERDOS-5-A4 and ERDOS-5-R1.
REVIEW_ALIAS_LETTER = "R"
ATTEMPT_ALIAS_LETTER = "A"


def contribution_alias_letter(contribution_type: str) -> str:
    if contribution_type not in CONTRIBUTION_TYPES:
        raise ValueError(f"unknown contribution type {contribution_type!r}")
    return REVIEW_ALIAS_LETTER if contribution_type in REVIEW_LIKE_TYPES else ATTEMPT_ALIAS_LETTER


CLAIM_TYPES = (
    "full_solution",
    "full_disproof",
    "partial_result",
    "conditional_result",
    "computational_evidence",
    "literature_report",
    "exploration",
)

TARGET_SCOPES = ("whole_statement", "part_of_statement", "special_case", "related_question")

CONTRIBUTION_MODES = ("human_only", "ai_only", "human_ai")
PROVENANCE_LEVELS = ("declared", "linked", "archived", "archived_attested", "platform_generated")

HUMAN_ROLES = (
    # CRediT (NISO Z39.104-2022)
    "conceptualization",
    "data_curation",
    "formal_analysis",
    "funding_acquisition",
    "investigation",
    "methodology",
    "project_administration",
    "resources",
    "software",
    "supervision",
    "validation",
    "visualization",
    "writing_original_draft",
    "writing_review_editing",
    # Platform additions
    "prompting",
    "submission",
)
MODEL_ROLES = (
    "generated_draft",
    "proof_search",
    "computation",
    "editing",
    "review_assistance",
    "translation",
    "other",
)
AUTHORSHIP_CONFIRMATION = ("confirmed", "listed_by_submitter", "declined")
# A legal declaration or authorship confirmation is never inferred from model output (§6).
DECLARATION_SOURCES = ("form_field", "comment_command", "cli_confirmation", "legacy_import")

REVIEW_FINDINGS = (
    "supports",
    "error_found",
    "gap_found",
    "counterexample",
    "known_result",
    "reproduced",
    "not_reproduced",
    "reference_suggestion",
    "comment",
)
OBJECTION_FINDINGS = frozenset({"error_found", "gap_found", "counterexample"})

RELATION_TYPES = (
    "subproblem_of",
    "generalises",
    "implies",
    "implied_by",
    "equivalent_to",
    "variant_of",
    "related",
    "duplicate_of",
    "promoted_from",
)
DERIVED_NATURES = ("restriction", "special_case", "step", "reformulation", "generalisation")

LINEAGE_RELATIONS = ("derivative_of", "extends", "responds_to", "possible_revision_of", "reuses")
LINEAGE_STATUSES = ("known", "unknown")

ARTIFACT_ROLES = (
    "manuscript",
    "manuscript_source",
    "bibliography",
    "figure",
    "data",
    "supplementary",
    "transcript",
    "formal_proof",
    "code",
    "notebook",
    "model",
    "dataset",
)
# Executable and large artifacts are linked, never hosted (§10).
LINK_ONLY_ARTIFACT_ROLES = frozenset({"formal_proof", "code", "notebook", "model", "dataset"})
# Roles only the platform assigns (renderer outputs and packages).
PLATFORM_ARTIFACT_ROLES = ("rendering", "package")
RECORD_ARTIFACT_ROLES = ARTIFACT_ROLES + PLATFORM_ARTIFACT_ROLES
ARTIFACT_AVAILABILITY = ("available", "unavailable", "withdrawn", "tombstoned")
ARTIFACT_LOCATIONS = ("in_repository", "release_asset", "external_pinned")
PIN_KINDS = ("git_commit", "hf_revision", "zenodo_doi", "swhid")

NORMALISED_SOURCE_STATUSES = (
    "open",
    "partially_solved",
    "solved",
    "proved",
    "disproved",
    "independent",
    "unknown",
    "other",
)

DISCIPLINE_STATUSES = ("planned", "pilot", "active")
# Statuses that accept new problems and contributions; planned disciplines go on hold (§14).
OPEN_DISCIPLINE_STATUSES = frozenset({"pilot", "active"})

# Ledger event types defined in schema version 1 (docs/adr/0006). Each has a payload
# schema in event.schema.json; later milestones add types with their payloads.
EVENT_TYPES = (
    "alias_reserved",
    "alias_bound",
    "alias_abandoned",
    "external_id_mapped",
    "statement_revised",
    "contribution_submitted",
    "revision_accepted",
    "revision_merged",
    "date_declared",
    "activity_recorded",
    "snapshot_built",
    "snapshot_activated",
)
# Where an event's occurred_at came from.
TIME_SOURCES = (
    "system_clock",
    "github_api",
    "git_committer_date",
    "git_author_date",
    "contributor_declaration",
    "legacy_header",
    "catalogue_source",
)
ACTOR_KINDS = ("person", "app", "system", "legacy_import")
DECLARED_DATE_KINDS = ("first_posted", "generation", "activity", "repository_first_added")
