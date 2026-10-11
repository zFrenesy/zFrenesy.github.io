# Acceptance matrix

Every acceptance test in spec §12 becomes an automated test or a scripted staging drill (§0). This table tracks where each one lives and how far it has got. Status as of milestone 1, 2026-10-11.

Legend: **covered** (an automated test exists and passes), **partial** (the part that can be tested in this milestone is covered), **planned**.

| # | Acceptance test (§12) | Where | Owner milestone | Status |
| --- | --- | --- | --- | --- |
| 1 | A fresh external contributor submits through an issue, answers missing metadata without writing YAML, and publishes without human approval | Staging drill (written in M3); intake tests | M3, M5 | Planned. M1 supplies the schemas and `publication_issues` the drill checks |
| 2 | Agent/local and fork-PR intake preserve attribution, commit authorship and original references through managed publication PRs | Staging drill; intake tests | M3 | Planned. M1 schemas carry `intake_refs` and actor IDs |
| 3 | Fifty concurrent sibling proposals obtain distinct permanent aliases; dropped or repeated workflow runs lose no accepted work | `tests/stress/test_ledger_concurrency.py` (`test_fifty_concurrent_sibling_proposals…` ×20 runs, `test_repeated_workflow_runs…`, `test_dropped_run_after_write…`) | M1 logic, M5 Git store | **Partial**: covered against the in-memory store; repeat against the Git-backed ledger in M5 |
| 4 | Two concurrent revisions with the same predecessor cannot silently overwrite each other | `test_concurrent_revisions_with_the_same_predecessor_cannot_both_advance`, `test_revisions_advance_only_from_the_current_head` | M1 logic, M5 | **Partial**: covered in memory; Git-backed drill in M5 |
| 5 | Changing metadata, target statement, source bytes, external-link pins or review context invalidates stale authorization | `tests/unit/test_fingerprint.py` (`test_stale_authorization_detection_end_to_end`, `test_every_binding_input_changes_k`) | M1 binding, M4 gate | **Partial**: covered for S and K; gate end-to-end in M4 |
| 6 | Workflow changes, malicious paths, hostile archives, forged reports, prompt injection, skipped jobs and neutral checks cannot gain merge or secret access | `tests/security/test_strict_yaml.py`, `test_ids_paths.py`, `test_fingerprint.py`, invalid fixtures; staging security drill | M1, M3, M4 | **Partial**: malicious paths and hostile YAML covered; the rest planned |
| 7 | Unpinned links, disallowed hosts, shortener and confusable-domain links are rejected; Hugging Face pickle weights are flagged | Invalid fixtures `unpinned-link`, `http-link`; `test_uri_format_is_strict`; `check_external_links` tests | M1 schema, M3 | **Partial**: pin format, HTTPS, userinfo and non-ASCII covered; hosts, shorteners, confusables and pickle in M3 |
| 8 | A later serious error yields a visible revision-specific objection; old packages and citations survive; favourable reviews do not transfer | Review schema targets an exact revision; site and package tests | M1 schema, M2, M3 | **Partial**: reviews bind to one exact revision (`contribution.review_target`) |
| 9 | A problem snapshot identifies all selected versions, rights, exclusions and checksum-valid assets; export/import works in a clean instance | Snapshot schema fixtures; `test_head_is_a_hash_chain_and_export_round_trips`; package tests; export tests | M1 schema, M2 packages, M5 downloads | **Partial**: snapshot contract and ledger export round-trip covered. Revision packages are built and checksummed locally in M2. Upload to Release assets and working downloads were moved to M5 by owner decision (2026-10-11) |
| 10 | Budget exhaustion queues work before spending beyond reserved limits; retries and fallbacks obey the same accounting; a 100-new-account swarm spends no more than the newcomer pool; the tripwire pauses only new-account screening | Spend-reservation stress tests | M4 | Planned. Budget values recorded in `platform.yaml` |
| 11 | Fault injection at every external side effect recovers without duplicate identities, fabricated dates or unnecessary AI calls | `test_dropped_run_after_write…` (identity); controller fault-injection suite | M1 partial, M5 | **Partial**: lost-response recovery covered for alias reservation |
| 12 | A second maintainer restores Git, ledger, packages, identity mappings and site from backups, rotates credentials and suspends publication | Restore drill runbook | M6 | Planned |

## Milestone 1 exit criteria

| Criterion | Evidence |
| --- | --- |
| Schemas for every record type, validated as JSON Schema 2020-12, with closed objects and vocabularies matching code | `tests/unit/test_schema_vocab.py` |
| Each failure mode rejected with a stable code | 54 invalid fixtures, `tests/unit/test_record_fixtures.py` |
| Identity rules: ID format, alias grammar and authorities, relations, paths | `test_ids_paths.py`, `test_aliases.py`, `test_relations.py` |
| Event model and ledger: idempotency, CAS, hash chain, rebuild, corruption detection | `test_ledger.py`, stress tests |
| Disciplines are configuration only | `test_dummy_discipline_end_to_end` |
| Deterministic fixtures for the §11 benchmark | `test_synthetic_fixture.py`, golden `tests/fixtures/golden/synthetic-seed-1.json` |
| Threat model, ADRs, staging checklist and settings verifier | `docs/threat-model.md`, `docs/adr/`, `operations/`, `test_verify_settings.py` |
| Staging organisation configured and verified | Owner applies `operations/staging-org.md`, then runs `python -m rp.ops.verify_settings` (all checks PASS) |
