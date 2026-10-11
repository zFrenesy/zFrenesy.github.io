# ADR 0010: Legacy migration rules

Status: Accepted, 2026-10-11 (milestone 2 plan; owner decisions on model names and scope)

## Context

Spec §12 requires an idempotent migration from the pinned legacy commit `b1f633121074e16579fa7fd05314e5f504d29bae`. It must preserve history, paths, notices, issue and review evidence, and source bytes. It must also keep a retained mapping from each source to its new identity, with evidence and uncertainty.

## Decision

**Source of truth.** The importer reads Git objects at the pinned commit (`git ls-tree`, `git cat-file --batch`), never the working tree. Historical review states come from `git log` on each review path.

**Classification.** Every one of the 9,965 files under `attacks/` gets exactly one class; anything else is reported as unclassified for owner review.

| Path | Class | Becomes |
| --- | --- | --- |
| `economics/statements/<JEL>-<n>.tex` | statement | `ECON-<JEL>-<n>` problem, `statement.tex` |
| `top_problems/definitions/<id>.tex` | statement | `TOP-<id>` problem, `statement.tex` |
| `erdos/<folder>/<n>[_vK].tex` without collection metadata | attempt | `legacy_record` on `ERDOS-<n>` |
| `erdos/GPT_6_Astra_Ultra/<n>.tex` with `COLLECTION_METADATA` | reused write-up | `legacy_record` with known `reuses` lineage to its source |
| `economics/<folder>/<JEL>-<n>[_vK].tex` | attempt | `legacy_record` on `ECON-…` |
| `top_problems/<folder>/<id>.tex`, `ENTRY_KIND` not `statement_only` | attempt | `legacy_record` on `TOP-<id>` |
| `top_problems/<folder>/<id>.tex`, `ENTRY_KIND: statement_only` (14 files) | statement copy in a model folder | Kept as a `legacy_record` with no claim, flagged uncertain for owner review |
| `top_problems/openai/<id>[_vK].tex` | external-claim summary | `legacy_record`, claim `literature_report`, pinned link to openai/math |
| `top_problems/Human_Contribution/<id>.tex` | human contribution | `legacy_record` with per-file overrides |
| `mo/<folder>/<qid>…tex` | attempt | `legacy_record` on `MO-<qid>` |
| `erdos/gpt_pro_5.4/IMPORTS.md`, `import_manifest.json` | import note | Provenance evidence for that folder; not a contribution |
| `reviews/<collection>/<id>.json` and every historical version | legacy review | Problem-level `legacy_record` with the raw label and its history |

**Problems.**

- Erdős: every number with an attempt (1,221). Statements are link-only stubs. Status comes from the pinned `erdos_status.json` as a `catalogue_source` observation.
- Top Open Problems: 4,177. The primary discipline comes from the legacy category:
  - `computer-science` goes to Computer Science;
  - `physics` goes to Mathematics, with Mathematical Physics as a secondary discipline;
  - everything else goes to Mathematics.

  Categories become topics; no classification codes are inferred.
- Economics: 657, with JEL classification.
- MathOverflow: the 103 catalogued questions plus any referenced question.

**Claims, not status.** `ATTEMPT_STATUS` values `solved`, `partial` and `unresolved` map to the claims `full_solution`, `partial_result` and `exploration`. They never change a source status. Legacy "solved (LLM claim)" fallbacks are not carried forward; the raw value stays in the record's extension.

**Lineage.** `_vK` siblings and same-folder pairs are not evidence of revision lineage. They get `possible_revision_of` with `lineage_status: unknown`. An explicit `REVISION_OF` header gives `derivative_of` with a known source revision. Reused write-ups get `reuses` to their declared `primary_source`.

**Model names (owner decision; migration only).**

- `rp/migration/legacy/models.yaml` maps each legacy folder to a model-use record. The `declared_name` is the label the legacy site showed (folder name with underscores as spaces). Provider and settings are stated explicitly per folder.
- Version is always `unknown`, provenance `declared`, evidence "legacy folder name, owner-confirmed". A `MODEL` header overrides the folder.
- This table exists only for the migration. The platform never infers a model from a folder or path for new contributions.

**Dates.**

- `FIRST_POSTED` becomes a `date_declared` event (`first_posted`, day precision, `legacy_header`).
- The first-addition Git author date becomes a `date_declared` event (`repository_first_added`, instant, `git_author_date`), applying the legacy rename rules (`attacks/erdos/` to `attacks/open_problems/erdos/`, and the `GPT_6_Astra_Ultra` folder rename).
- `FIRST_POSTED: null` gives no event. Neither date is ever a publication date.

**Reviews.**

- Each current and historical state of a legacy review JSON becomes a version in a problem-level `legacy_record`. It records the raw label, note, citations, `reviewed_by`, issue number and URL.
- Reviewer, issue author and labeller are separate fields. The issue author and labeller come from a cached read-only API snapshot; where the API is unavailable they are recorded as `unknown`.
- No contribution revision is marked disputed automatically.

**Identity mapping.**

- `migration/legacy-b1f6331/mapping.jsonl` has one line per source blob or record. It gives source repository, commit, path, blob SHA, class, entity ID, revision ID, alias, evidence and uncertainty.
- The importer reads an existing mapping first and reuses every identifier, so repeated runs produce byte-identical output. Unsafe filenames (spaces) get a safe `files/` name; the original path stays in the mapping.

## Consequences

The migrated tree is fully regenerable from the pinned commit plus the mapping. The 14 odd `statement_only` copies and the external-claim summaries' contribution mode (recorded as `ai_only` with an unknown model) are listed in the inventory report for owner confirmation.
