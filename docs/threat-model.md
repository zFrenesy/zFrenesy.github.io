# Threat model

Status: milestone 1 baseline, 2026-10-11. Review at every milestone sign-off and whenever a trust boundary changes.

Scope: the platform described in `docs/IMPLEMENTATION_SPEC.md`, covering `we-solve/we-solve.github.io`, `we-solve/research` (including `automation-ledger`), the two GitHub Apps, the AI screening job, rendering, Pages and the legacy archive. "M1"–"M6" refer to the milestones in spec §12.

## 1. Assets

| Asset | Why it matters |
| --- | --- |
| A1 Merge authority on `research/main` | Publication into the archive; the core invariant is that only an explicit, deterministic authorization exercises it (§6, §7). |
| A2 Ledger integrity (`automation-ledger`) | Identities, aliases, revision heads, decisions and spend records; everything else can be rebuilt from it. |
| A3 Publisher App private key | Can mint tokens with every Publisher permission (§7). |
| A4 AI provider credentials and budget | Money; the monthly cap and newcomer pool (§8). |
| A5 Alias and identity namespace | Permanent citations; must never collide or be recycled. |
| A6 Published site, packages and citations | Readers' trust; old packages must survive later errors. |
| A7 Attribution and personal data | Credit, consent, privacy. |
| A8 Legacy archive `mehmetmars7/Erdosproblems-llm-hunter` | Preserved history; never modified by this project. |
| A9 Platform repository and CI | Code and policy that every decision depends on. |

## 2. Adversaries and failure sources

- **Malicious contributor:** submits hostile files, metadata, links or prompt injections, or tries to steer screening.
- **Swarm of fresh accounts:** tries to drain the AI budget or flood moderation.
- **Abusive reviewer:** harassment, brigading, or false objections to block publication.
- **Compromised dependency or action** in the supply chain.
- **Compromised or confused automation:** a workflow that runs untrusted code with secrets, or a stale or forged check.
- **Honest operational failure:** crashes, dropped or repeated workflow runs, API errors, provider outages, scheduled workflows disabled after 60 days.
- **Maintainer error:** settings drift, a mistaken force push, a lost key.
- **The model itself:** a fallible component that can be wrong or manipulated. It holds no authority, so the invariant is "LLM output cannot exercise repository authority", not "LLM output cannot cause a bad admission".

## 3. Trust boundaries

| Boundary | What crosses it | Principal controls (spec) | Milestone |
| --- | --- | --- | --- |
| B1 Contributor → intake (issues, fork PRs, `rp submit`) | Untrusted text, files, YAML, links | Strict YAML, closed schemas, path and size rules, link policy, no execution (§4, §7, §10) | M1 parsers and schemas; M3 intake |
| B2 Intake → candidate PR | Validated content, the contributor's original commits | Bot-owned candidate, Intake App without merge or ledger rights (§6, §7) | M3 |
| B3 Candidate → extraction and rendering | Manuscripts, archives | Sandbox: no secrets, no network, bounded resources, fresh runner (§7) | M2 render, M3 extract |
| B4 Candidate → AI screening | Bounded text, the review context | Provider key only, no repository write, no tools; report as an artifact (§7, §8) | M4 |
| B5 Screening → authorization | Screening report | Verified origin, run, revision, schema and digest; K must match; explicit `success` only (§6, §7) | M1 K; M4 gate |
| B6 Controller → `main` and ledger | Merge, ledger events | Publisher App, serialised controller, rulesets, compare-and-swap ledger writes (§6, §7, §9) | M1 ledger logic; M4 Apps and rulesets; M5 controller |
| B7 Controller → Pages and Releases | Site, packages | Pinned build, immutable assets, separately recorded activation (§9, §11) | M2, M5 |
| B8 Site → readers | Rendered pages, links | Sanitised HTML, no raw HTML, no trackers, safe link attributes (§10, §19) | M2 |
| B9 Platform repo ← dependencies and actions | Code | Hash-locked dependencies, SHA-pinned actions, org allowlist, Dependabot (§2, §21) | M1 |
| B10 Agent workspace ← research repo | Prior work as context | Quoted as untrusted; research-supplied agent files are never imported (§7, §20) | M3 |

## 4. Threats and controls

Status: **done**, meaning implemented and tested in M1; **partial**; or **planned**, with its milestone.

| ID | Threat | Boundary | Control | Status / test |
| --- | --- | --- | --- | --- |
| T1 | A contribution PR changes workflows or configuration and gains secrets, e.g. through `pull_request_target` running PR code | B1, B6 | Path allowlist; protected default-branch workflows; never check out or run PR code; Intake and Publisher Apps separated; rulesets | Planned M3/M4; security drill |
| T2 | Malicious paths: traversal, absolute paths, symlinks, submodules, hidden or executable files | B1 | `check_relative_path`, schema path patterns, manifest rejects modes 120000/160000 and paths outside `files/`, symlinks refused on disk | **Done**: `tests/unit/test_ids_paths.py`, `test_fingerprint.py`, invalid fixtures |
| T3 | Hostile YAML: billion laughs, tags such as `!!python/object`, duplicate keys, silent coercion (`NO`, `5.10`) | B1 | `rp.strict_yaml` | **Done**: `tests/security/test_strict_yaml.py` |
| T4 | Hostile archives: zip bombs, nested archives, path tricks inside zips | B1, B3 | Expansion limits (25 MiB total, 200 files), sandboxed extraction | Planned M3 |
| T5 | Forged or replayed screening report | B5 | Report bound to S and the review context; K recomputed from current inputs; artifact origin and run verified | Partial: K and S **done** (`test_fingerprint.py`); verification M4 |
| T6 | Prompt injection in a manuscript steers the reviewer | B4 | Model has no tools or authority; text addressed to the reviewer is a blocking category; deterministic `authorize` | Planned M4 |
| T7 | Neutral, skipped, missing or stale checks pass as success | B5, B6 | Only explicit `success` authorises; the finalizer evaluates every stage; failures are fail-closed | Planned M4 |
| T8 | Authorization reused after content changes | B5 | S covers metadata, attribution, targets, dependencies, exact bytes and pins; K adds PR, head, base, policy, rubric, context and editor state | **Done** at binding level: `test_stale_authorization_detection_end_to_end`; gate M4 |
| T9 | Concurrent revisions overwrite each other | B6 | Expected predecessor plus compare-and-swap appends; `StalePredecessor` | **Done** (logic): `tests/stress/test_ledger_concurrency.py`; Git store M5 |
| T10 | Alias collision, recycling or squatting | B6 | Single global namespace, monotonic counters, burned abandoned aliases, one live alias per entity, exact lookup | **Done**: `test_aliases.py`, stress tests |
| T11 | Repeated or dropped workflow runs duplicate identities or lose work | B6 | Request-derived idempotency keys; re-plan on a stale head | **Done** (logic): stress tests; fault injection M5 |
| T12 | Ledger tampering or force push | B6 | Ruleset lets only the Publisher write `automation-ledger`; hash-chained head; off-account mirrors | Partial: hash chain **done**; ruleset M4; mirrors M6 |
| T13 | Publisher key leaks to untrusted jobs | B4, B6 | Key released only to the controller environment, never to intake, extraction, screening or rendering | Planned M4 (environments created in staging now) |
| T14 | Budget drain by a swarm or retry loop | B4 | Worst-case reservations before each call, newcomer pool, per-account quotas, tripwire, kill switch, provider caps | Planned M4; kill switch configured off (`screening_enabled: false`) |
| T15 | Credentials or personal data published | B1 | Scanning (no guarantee claimed), public-submission warning, takedown | Planned M3/M4 |
| T16 | Invisible or reordering characters (bidirectional overrides, control characters) in metadata | B1, B8 | Text checks on authored records | **Done**: invalid fixtures `bidi-override-title`, `control-character` |
| T17 | Script injection through rendered Markdown, TeX or SVG | B3, B8 | Pandoc restricted profile, raw HTML disabled, sanitiser, SVG not accepted as a figure format | Planned M2 (SVG excluded from accepted formats now) |
| T18 | Unsafe external links: unpinned, shorteners, raw IPs, confusable domains, pickle weights | B1, B8 | Schema requires `https` and pin formats; URI format rejects userinfo and non-ASCII; host allowlist and Hub API checks in `check_external_links` | Partial: schema **done** (invalid fixtures `unpinned-link`, `http-link`, `test_uri_format_is_strict`); M3 |
| T19 | A model fabricates a legal declaration or authorship confirmation | B1, B4 | Declaration `source` cannot be model extraction; actor must be the submitter; quote grounding for extracted values | Partial: schema **done**; grounding M3 |
| T20 | People listed without consent | B1 | `listed_by_submitter` until `/confirm-authorship`; `declined` blocks publication | Partial: data model and `publication_issues` **done**; command M3 |
| T21 | A contributor changes a problem's source status or claims catalogue authority | B1 | Separate status axes; `sources` provenance limited to catalogue sync, curator or legacy import; the gate compares with trusted state | Partial: schema **done**; gate M4 |
| T22 | Supply-chain compromise (dependency or action) | B9 | Hash-locked dependencies, SHA-pinned actions, two-week minimum age for new pins, org allowlist with SHA pinning required | **Done** for CI and lock; org settings via checklist |
| T23 | Scheduled reconciliation silently stops (60-day rule) | B6 | External health check and runbook | Planned M5/M6 |
| T24 | Fabricated or future timestamps; claimed dates presented as publication dates | B6, B7 | Snapshots carry `built_at` only; activation is a separate event; declared dates keep precision and source | **Done**: snapshot schema, event checks, synthetic fixture |
| T25 | Review harassment, brigading, endless objections | B1 | Review screening, rate limits, penalties, tombstones, 90-day "response given" rule | Planned M3/M4 |
| T26 | Confusable aliases or identifiers | B6 | Aliases are upper-case ASCII; identifiers are lowercase hex | **Done**: grammar tests |
| T27 | Resource exhaustion through large metadata | B1 | 256 KiB and depth-32 YAML limits; schema `maxItems` and `maxLength` | **Done** |
| T28 | Tools execute research content (CLI, agents) | B10 | `rp` never executes manuscripts, imported agent files or model output; context is quoted | **Done** for current CLI; `rp start` M3 |
| T29 | Legacy archive modified | — | Read-only use of the pinned snapshot; no credentials for it in automation | Process rule (CLAUDE.md); importer M2 |
| T30 | Loss of the sole account or credentials | — | Second owner, mirrors, restore drill, credential succession | Planned M6 |

## 5. Residual risks

- Screening can admit a wrong or low-quality attempt. Publication means admission to an attributed archive, not correctness (§1), and pages say so (§18).
- GitHub-hosted runners, GitHub's permission model and provider billing are trusted. Their failure modes are mitigated by fail-closed checks and spend caps, not eliminated.
- Until a second owner exists, the owner is a single point of failure for keys and settings.
- Settings drift between applying the checklist and running the verifier. Re-run `python -m rp.ops.verify_settings` at every milestone sign-off.
