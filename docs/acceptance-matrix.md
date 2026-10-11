# Acceptance matrix

Every acceptance test in spec §12 becomes an automated test or a scripted staging drill (§0). This table tracks where each one lives and how far it has got. Status as of milestone 2 local implementation, 2026-10-11. Local tests and benchmark results do not establish that staging settings, deployment, or the complete legacy-corpus build have passed.

Legend: **covered** (an automated test exists and passes), **partial** (the part that can be tested in this milestone is covered), **planned**.

| # | Acceptance test (§12) | Where | Owner milestone | Status |
| --- | --- | --- | --- | --- |
| 1 | A fresh external contributor submits through an issue, answers missing metadata without writing YAML, and publishes without human approval | Staging drill (written in M3); intake tests | M3, M5 | Planned. M1 supplies the schemas and `publication_issues` the drill checks |
| 2 | Agent/local and fork-PR intake preserve attribution, commit authorship and original references through managed publication PRs | Staging drill; intake tests | M3 | Planned. M1 schemas carry `intake_refs` and actor IDs |
| 3 | Fifty concurrent sibling proposals obtain distinct permanent aliases; dropped or repeated workflow runs lose no accepted work | `tests/stress/test_ledger_concurrency.py` (`test_fifty_concurrent_sibling_proposals…` ×20 runs, `test_repeated_workflow_runs…`, `test_dropped_run_after_write…`) | M1 logic, M5 Git store | **Partial**: covered against the in-memory store; repeat against the Git-backed ledger in M5 |
| 4 | Two concurrent revisions with the same predecessor cannot silently overwrite each other | `test_concurrent_revisions_with_the_same_predecessor_cannot_both_advance`, `test_revisions_advance_only_from_the_current_head` | M1 logic, M5 | **Partial**: covered in memory; Git-backed drill in M5 |
| 5 | Changing metadata, target statement, source bytes, external-link pins or review context invalidates stale authorization | `tests/unit/test_fingerprint.py` (`test_stale_authorization_detection_end_to_end`, `test_every_binding_input_changes_k`) | M1 binding, M4 gate | **Partial**: covered for S and K; gate end-to-end in M4 |
| 6 | Workflow changes, malicious paths, hostile archives, forged reports, prompt injection, skipped jobs and neutral checks cannot gain merge or secret access | `tests/security/test_strict_yaml.py`, `test_ids_paths.py`, `test_fingerprint.py`, `test_site_build.py`, `test_site_checks.py`, invalid fixtures; staging security drill | M1, M2, M3, M4 | **Partial**: malicious paths, hostile YAML, site-output traversal, symlinks and remote HTML/CSS subresources covered; merge/secret-access gate and staging drill remain planned |
| 7 | Unpinned links, disallowed hosts, shortener and confusable-domain links are rejected; Hugging Face pickle weights are flagged | Invalid fixtures `unpinned-link`, `http-link`; `test_uri_format_is_strict`; `check_external_links` tests | M1 schema, M3 | **Partial**: pin format, HTTPS, userinfo and non-ASCII covered; hosts, shorteners, confusables and pickle in M3 |
| 8 | A later serious error yields a visible revision-specific objection; old packages and citations survive; favourable reviews do not transfer | Review schema targets an exact revision; `test_site_build.py`, `test_packages.py`, `test_site_references.py` | M1 schema, M2, M3 | **Partial**: reviews bind to one exact revision (`contribution.review_target`); generated citations name immutable revision URLs; available source/package bytes are preserved. A historical revision whose source snapshot is absent receives a labelled placeholder, never the current manuscript. Later-objection intake and persistent Release delivery remain planned |
| 9 | A problem snapshot identifies all selected versions, rights, exclusions and checksum-valid assets; export/import works in a clean instance | Snapshot schema fixtures; `test_head_is_a_hash_chain_and_export_round_trips`; `test_packages.py`, `test_site_build.py`; export tests | M1 schema, M2 packages, M5 downloads | **Partial**: snapshot contract and ledger export round-trip covered. Revision packages are built, checksummed and tested for exact source bytes and rights locally in M2, outside Pages. Upload to Release assets and working downloads were moved to M5 by owner decision (2026-10-11) |
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

## Milestone 2 local evidence

| Criterion | Evidence and remaining work |
| --- | --- |
| Preserve imported source bytes, rights, attribution and legacy status distinctions | `tests/unit/test_migration.py`; importer-based `test_site_build.py` checks all eight synthetic problems and 13 contributions, exact permitted source downloads and package contents, ShareAlike statement rights, human/model roles and independent source-status/claim display. Statements/contributions with `link_only` or `unclear` redistribution remain metadata/source links; their source bodies are not rendered, downloaded or packaged |
| Generate discipline, problem, contribution, person, model and immutable revision routes | `rp/site/build.py`, Jinja templates, `test_site_build.py`; project Pages prefix `/research/` exercised with real rendering and Pagefind generation |
| Preserve the extracted renderer and fail visibly for unsupported passages | `test_render.py`, `test_vendor.py`, copied legacy JavaScript regression tests; build-time escaped source boxes, HTML sanitisation and browser MathJax error fallbacks. Scope and body independently retain successful output or escaped fallback; labels, mathematical content and diagnostics account for both. This is compatibility coverage, not a complete TeX interpreter or a proof of visual fidelity for every manuscript |
| Resolve references by document, immutable revision and imported source scope | `test_site_references.py`; actual `Builder.render_documents` integration covers known exact lineage, unknown possible revisions, wrong revision targets, ambiguous declared sources, local precedence and target-independent rendering order |
| Avoid replacing unavailable historical sources with current content | `test_older_revision_placeholder_never_substitutes_current_sources`; ledger `sequence_label` creates an explicit placeholder without a source directory or citation package for the unavailable snapshot |
| Keep research inputs and the legacy repository unchanged by site generation | Build fixture hashes both its synthetic legacy repository and imported input tree before and after generation. Output-under-input and source traversal/symlink attempts fail. Tests use synthetic legacy history, never the live legacy repository |
| Enforce static publication checks and payload budgets | `test_site_checks.py`: route/anchor integrity, duplicate IDs, mandatory assets including dynamically declared MathJax engines, HTML/SVG/CSS remote subresources, safe paths, ZIP/PDF exclusion, 200 KiB initial payload and 800 MiB total output gates. JavaScript-created requests additionally need browser verification |
| Produce deterministic website content and revision packages | Repeated fixture builds produce byte-identical first-party pages, assets, sources, citations and ZIP packages. Pagefind 1.5.2 filter ordering changes generated search-index hashes and small byte totals; its index is validated each run but is not asserted byte-identical |
| Meet the §11 synthetic scale target | Measured 500-attempt / 200-contributor / 30-subproblem fixture; results below |
| Separate the trusted build from deployment privileges | `.github/workflows/pages.yml` and `operations/milestone-2.md`: exact platform/research/ledger inputs, read-only build job, network-disabled build step and separate staging Pages deploy job. Workflow/settings/deployment success requires its own recorded run |
| Record local test outcomes | Final aggregate `python -m pytest` on 2026-10-11: **615 passed, one optional `RP_LEGACY_CLONE` test skipped**, 56.01 seconds, after the source-integrity, model, rendering and synthetic-fixture fixes. The focused site/build/render subset also passed all 94 tests. CI remains pending |
| Complete staging publication and live smoke checks | Pending recorded settings verification, successful workflow/deploy result and live checks; local fixture success is not deployment evidence |

### Verification checkpoints

The final local suite and strict archive load include the rights, source-integrity, model, rendering and synthetic-fixture fixes. The initial whole-site build below predates the final refinements; its output metrics do not establish that the final complete site or CI deployment has passed.

| Checkpoint on 2026-10-11 | Recorded result |
| --- | --- |
| Final aggregate local suite | 615 passed, one optional `RP_LEGACY_CLONE` test skipped, 56.01 seconds |
| Final strict load of the complete imported archive | 6,155 problems, 5,154 contributions and 56,381 ledger events validated successfully |
| Initial complete legacy-corpus site build | 6,155 problems, 5,154 contributions and 9,963 rendered TeX documents |
| Initial complete legacy-corpus rendering report | Zero formatter errors; 252 documents containing 362 explicit source boxes. This does not claim that every mathematical expression renders correctly in browsers |
| Initial complete legacy-corpus publication checks | 29,666 HTML pages, 84,934 files, 477,623,777 output bytes; largest initial payload 173,320 bytes; no static link/asset/budget errors |
| Final complete site build, CI and staging deployment | Awaiting their own successful build, CI, settings and live-site evidence; the final local suite and strict archive load above are complete |

## Synthetic site benchmark

One local run on 2026-10-11 used `tests.fixtures.synthetic.generate(..., seed="1", attempts=500, contributors=200, subproblems=30, reviews=60)` and the real builder with search enabled, an empty renderer cache, separate temporary revision-package output, and base URL `https://example.github.io/research/`. No linked artifact was fetched and no paid provider was used.

| Measurement | Result |
| --- | --- |
| Source records | 105 problems, including 30 derived subproblems; 560 contributions: 500 attempts and 60 reviews |
| People and history | 201 people, including the fixture's legacy owner; 54 contributions with multiple accepted revisions |
| Fixture generation | 6.41 seconds |
| Site build, Pagefind, validation and 510 local revision packages | 18.04 seconds |
| Redistribution gate | 50 legacy records with unclear rights remain metadata; their source bodies and ZIPs are not published |
| Generated HTML pages / total Pages files | 2,487 / 6,743 |
| Pages bytes, excluding revision ZIPs | 23,745,163 bytes (22.65 MiB) |
| Largest initial first-party payload | `search/index.html`: 173,884 bytes (169.81 KiB), below 200 KiB |
| Link, asset and budget validation | No errors |
| Local toolchain | Python 3.13.0, Node 23.1.0, Pagefind 1.5.2 on the development machine |

This is one measured synthetic run, not a throughput guarantee or a full-corpus result. CI selects Python 3.12.14 and Node 22.23.3; its result must be recorded independently. The local JSON report is retained with that run's temporary artifacts; release evidence should retain the corresponding build report through the workflow's evidence artifact.
