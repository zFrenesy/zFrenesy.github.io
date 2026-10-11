# Acceptance matrix

Every acceptance test in spec §12 becomes an automated test or a scripted staging drill (§0). This table tracks where each one lives and how far it has got. Status as of milestone 2, 2026-10-11: the code test suite, strict archive load, complete-corpus CI build, all 28 staging settings checks, staging deployment and live-browser checks have passed. The recorded evidence and remaining limitations appear below.

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
| Staging organisation configured and verified | `python -m rp.ops.verify_settings --org we-solve-staging`: all 28 checks passed on 2026-10-11 |

## Milestone 2 evidence

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
| Record test outcomes | Initial local aggregate: **615 passed, one optional `RP_LEGACY_CLONE` test skipped**, 56.01 seconds. Final code CI [run 38159866973](https://github.com/we-solve-staging/we-solve-staging.github.io/actions/runs/38159866973), including the accepted-package-fingerprint regression: **616 passed, one optional test skipped**, 107.96 seconds, at commit `17c88624563ab81cba3ab714df4f38b9469593d3`. The final Pages workflow repeated the same suite: **616 passed, one optional test skipped**, 86.49 seconds |
| Complete staging publication and live smoke checks | All 28 settings checks and the complete-corpus CI build passed. Final deployment [38159873246](https://github.com/we-solve-staging/we-solve-staging.github.io/actions/runs/38159873246) succeeded. The detailed live-browser audit and final published-asset/destination recheck passed; scope and results below |

### Verification checkpoints

The final [staging run 38159873246](https://github.com/we-solve-staging/we-solve-staging.github.io/actions/runs/38159873246), at platform commit `17c88624563ab81cba3ab714df4f38b9469593d3`, built and deployed successfully. Its build job took 7 minutes 44 seconds (17:35:56–17:43:40 UTC), followed by a 30-second deployment (17:43:43–17:44:13 UTC). Its `site-build-evidence` artifact supplies `inputs.json` and `site-report.json`; the compact snapshot below records those final build results.

| Checkpoint on 2026-10-11 | Recorded result |
| --- | --- |
| Initial aggregate local suite | 615 passed, one optional `RP_LEGACY_CLONE` test skipped, 56.01 seconds |
| Final code CI suite | 616 passed, one optional test skipped, 107.96 seconds; [run 38159866973](https://github.com/we-solve-staging/we-solve-staging.github.io/actions/runs/38159866973) |
| Final Pages workflow test suite | 616 passed, one optional test skipped, 86.49 seconds |
| Final strict load of the complete imported archive | 6,155 problems, 5,154 contributions and 56,381 ledger events validated successfully |
| Final complete-corpus CI build | 6,155 problems, 5,154 contributions and 9,963 rendered TeX documents; 5,154 permitted revision packages generated outside Pages |
| Final rendering report | Zero body or scope conversion errors; 252 documents containing 362 explicit source boxes. This does not claim that every mathematical expression renders correctly in browsers |
| Final reference diagnostics | 331: 325 unresolved references, five ambiguous references and one duplicate-label diagnostic. These remain explicit diagnostics rather than guessed links |
| Final publication checks | 29,666 HTML pages, 83,566 files, 503,016,444 output bytes (479.71 MiB); largest initial payload `search/index.html`, 173,841 bytes (169.77 KiB); no static link/asset/budget errors |
| CI toolchain | Python 3.12.14, Node 22.23.3, Pagefind 1.5.2 |
| Staging settings | All 28 checks passed |
| Live-browser audit | All 14 browser checks passed over 19 page/viewport visits, with separate keyboard/resize checks for three manuscripts; details below |
| Final staging deployment and recheck | [Run 38159873246](https://github.com/we-solve-staging/we-solve-staging.github.io/actions/runs/38159873246) succeeded. At 17:44:49 UTC, all four published frontend assets matched the final checkout and seven representative destinations returned HTTP 200 without unexpected redirects |

Only this compact JSON summary is retained here; the multi-megabyte per-document/package report stays in the workflow artifact. Input commits identify the reviewed build independently of subsequent documentation changes.

```json
{
  "schema_version": 1,
  "date": "2026-10-11",
  "run_url": "https://github.com/we-solve-staging/we-solve-staging.github.io/actions/runs/38159873246",
  "build_status": "success",
  "deployment_status": "success",
  "settings_checks_passed": 28,
  "inputs": {
    "platform_commit": "17c88624563ab81cba3ab714df4f38b9469593d3",
    "research_repository": "we-solve-staging/research",
    "research_commit": "547341f69bcbf05c1e17824722793bad37efae96",
    "ledger_commit": "e383f8236bf4f62b81e6e07219d83a2bacafddc0",
    "base_url": "https://we-solve-staging.github.io/",
    "python": "3.12.14",
    "node": "v22.23.3",
    "pagefind": "1.5.2"
  },
  "renderer": "sha256:7fc8e4989d2b95bbb47c31391e05147250a138f0036ffb32a67114ea2d0c7e83",
  "problems": 6155,
  "contributions": 5154,
  "revision_packages_outside_pages": 5154,
  "rendering": {"documents": 9963, "errors": 0, "scope_errors": 0, "documents_with_source_boxes": 252, "source_boxes": 362},
  "reference_diagnostics": {"unresolved_reference": 325, "ambiguous_reference": 5, "duplicate_label": 1},
  "checks": {"html_pages": 29666, "files": 83566, "total_bytes": 503016444, "max_initial_payload_bytes": 173841, "errors": []}
}
```

### Live-browser audit

The live [staging site](https://we-solve-staging.github.io/) from responsive deployment [38159644477](https://github.com/we-solve-staging/we-solve-staging.github.io/actions/runs/38159644477), platform commit `222307db5da17c476688fa2ce7ee888dfb620f3b`, passed all **14 automated browser checks across 19 page/viewport visits** on 2026-10-11. The four published frontend assets (`site.css`, `site.js`, `mathjax-init.js`, `search.js`) matched the final checkout byte-for-byte. The subsequent `17c88624563ab81cba3ab714df4f38b9469593d3` change affects backend package fingerprints. After that final deployment succeeded, a recheck at 17:44:49 UTC confirmed the same four assets and seven representative destinations: home, search, problem, latest contribution, immutable contribution, CSL-JSON and the build API. All returned HTTP 200 without unexpected redirects; the citation retained its canonical revision URL and ID.

| Browser check | Result |
| --- | --- |
| Page loading and layouts | All 19 visits returned HTTP 200. Desktop width 1,440 px and mobile width 375 px had no page-level horizontal overflow; the homepage was checked in light and dark modes |
| Five representative collections | Erdős (`ERDOS-5`), MathOverflow (`MO-339137`), Oberwolfach (`TOP-30002919`), Top Open Problems (`TOP-6`) and Economics (`ECON-C73-1`) |
| Mathematical display | Sampled manuscripts `TOP-6-A1/r1`, `ECON-C73-1-A2/r1` and `ERDOS-39-A4/r1` rendered 1,877, 334 and 376 expressions respectively, with matching assistive-MathML counts and no visible engine-error nodes. Unsupported passages remained explicit source boxes. Long and numbered equations stayed within the 375 px page layout |
| Reference navigation | Clicked references in all three sampled manuscripts reached existing anchors in the intended immutable revision |
| Source bytes | Downloaded the original `.tex` source for each of those three revisions; all three byte counts and SHA-256 digests matched the accepted local source |
| Citation identity | `TOP-6-A1/r1` CSL-JSON retained ID `wesolve:TOP-6-A1-r1`, the matching title, alias/revision and canonical immutable URL |
| Rights and publication state | Erdős/MathOverflow statements remained source links without statement downloads. Rights notices were visible for permitted statements. Release downloads were not advertised before publication |
| Search | 11,309 indexed documents. The live UI returned 107 results for `Hodge`; the Economics filter returned 1,027 results for `equilibrium` and worked at 375 px |
| Requests and failures | No third-party requests, resource failures or browser/console errors were observed. The homepage made no MathJax requests |
| Keyboard operation and resize of wide equations | Passed for all three sampled manuscripts: 34, 17 and 20 local equation scrollers respectively. Each tested scroller was keyboard-focusable and ArrowRight advanced its scroll position (15, 40 and 40 px). At 375 px every page's scroll width remained 375 px; resizing to 1,440 px preserved manuscript text and matching assistive MathML, without page overflow. This focused check does not establish full WCAG conformance |

```json
{
  "browser_run_url": "https://github.com/we-solve-staging/we-solve-staging.github.io/actions/runs/38159644477",
  "status": "success",
  "checks_passed": 14,
  "page_viewport_visits": 19,
  "collections": 5,
  "original_source_downloads_verified": 3,
  "frontend_assets_byte_identical": 4,
  "indexed_documents": 11309,
  "hodge_results": 107,
  "equilibrium_economics_results": 1027,
  "page_overflows": 0,
  "external_requests": 0,
  "resource_failures": 0,
  "browser_errors": 0,
  "keyboard_audit_status": "success",
  "keyboard_audit_scope": "wide_equation_scrolling_and_resize",
  "keyboard_manuscripts_checked": 3,
  "final_deployment_run_url": "https://github.com/we-solve-staging/we-solve-staging.github.io/actions/runs/38159873246",
  "final_deployment_recheck_at": "2026-10-11T17:44:49.525Z",
  "final_deployment_recheck_status": "success",
  "final_deployment_assets_verified": 4,
  "final_deployment_destinations_verified": 7
}
```

### Remaining rendering follow-up

Imported metadata titles are displayed as plain text and can retain TeX dollar delimiters; the MathOverflow title for `MO-339137`, for example, includes `$0,1$`. Browser math typesetting currently targets document containers, so the successful manuscript audit does not establish mathematical typesetting in metadata titles. This remains a rendering follow-up, alongside the explicit unsupported-source and unresolved-reference diagnostics above.

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

This is one measured synthetic run, not a throughput guarantee. The complete-corpus CI result above was measured independently using Python 3.12.14 and Node 22.23.3. The local synthetic JSON report is retained with that run's temporary artifacts; release evidence retains the corresponding build report through the workflow's evidence artifact.
