# ADR 0007: Claim types, roles and other vocabularies

Status: Accepted, 2026-10-11 (proposed in the milestone 1 plan; the owner may revise at milestone sign-off)

## Context

The spec names several fields without fixing their values: claim types, human roles, model-use roles, target scope, lineage relations and normalised source status. The values live in `rp/vocab.py` and are repeated in the schemas. A test keeps the two identical.

## Decision

| Vocabulary | Values |
| --- | --- |
| Claim type | `full_solution`, `full_disproof`, `partial_result`, `conditional_result`, `computational_evidence`, `literature_report`, `exploration` |
| Target scope | `whole_statement`, `part_of_statement`, `special_case`, `related_question` |
| Human roles | The 14 CRediT roles (NISO Z39.104-2022) plus `prompting` and `submission` |
| Model-use roles | `generated_draft`, `proof_search`, `computation`, `editing`, `review_assistance`, `translation`, `other` |
| Authorship confirmation | `confirmed`, `listed_by_submitter`, `declined` |
| Declaration source | `form_field`, `comment_command`, `cli_confirmation`, `legacy_import` (never model extraction) |
| Lineage relation | `derivative_of`, `extends`, `responds_to`, `possible_revision_of`, `reuses`; status `known` or `unknown` |
| Normalised source status | `open`, `partially_solved`, `solved`, `proved`, `disproved`, `independent`, `unknown`, `other`; the raw status is always kept |
| Artifact role | `manuscript`, `manuscript_source`, `bibliography`, `figure`, `data`, `supplementary`, `transcript`; link-only `formal_proof`, `code`, `notebook`, `model`, `dataset`; platform-only `rendering`, `package` |

Rules attached to these vocabularies:

- A claim is required for `attempt` and `counterexample`. It is optional for `correction`, `replication` and `legacy_record`, and absent for review-like types, which carry a `review` block.
- An `ai_only` contribution may list humans only in the `prompting` or `submission` roles. Any other human role makes it `human_ai`.
- The submitter is the authenticated actor and is always `confirmed`. People the submitter lists stay `listed_by_submitter` until they confirm with `/confirm-authorship`. A `declined` person blocks publication.

**Legacy mapping (milestone 2).** `ATTEMPT_STATUS` values `solved`, `partial` and `unresolved` map to the *claims* `full_solution`, `partial_result` and `exploration`. They never become a source status. A `Human_Contribution` folder or a `_v2` suffix is not evidence of mode or lineage: such records get `lineage_status: unknown` and a `possible_revision_of` relation.

## Consequences

Validators reject values outside these lists. Any change, including adding a value, therefore needs a schema version bump, and removing or renaming a value also needs a migration of stored records. Batch such changes at milestone boundaries.
