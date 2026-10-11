# AI-assisted research platform — implementation specification for Claude Code

Status: approved-for-planning architecture specification. It is not permission to change production systems.
Review date: 2026-10-11. Supersedes earlier handoff drafts.

# Part I — Architecture and machinery

## 0. How Claude Code should use this document

- Treat this file as the source of truth. Place it at `docs/IMPLEMENTATION_SPEC.md` in the platform repository and reference it from `CLAUDE.md` (a starter is provided alongside this file).
- Start each milestone in plan mode: read the relevant sections, propose a plan with files and tests, and wait for the owner's approval before writing code.
- Work in a staging GitHub organisation against the pinned legacy snapshot (§11). Never modify, transfer, or push to `mehmetmars7/Erdosproblems-llm-hunter`.
- Do not create GitHub Apps, secrets, rulesets, billing settings, or provider spend limits yourself. Write the exact settings as a checklist in `operations/` for the owner to apply, then verify them by reading the configuration through the API.
- Never call paid AI APIs in tests. Provider adapters must have a recorded-fixture mode and a fake provider; live calls happen only in staging with an owner-supplied key and a hard reservation cap.
- Prefer small, reviewable commits with tests. Every acceptance test in §12 becomes an automated test or a scripted staging drill.
- If this specification is ambiguous or conflicts with what GitHub or a provider actually supports, stop and ask instead of improvising. Record decisions as ADRs in `docs/adr/`.

## 1. Mission and release boundary

Build an integrated Mathematics and Economics research collaboration site. Ordinary, admissible research submissions, revisions, proposed problems, subproblems, and voluntary reviews must proceed through automated metadata clarification, AI screening, deterministic authorization, automatic merging, packaging, and website publication without mandatory human approval.

Publication means admission to an attributed research archive. It does not mean scientific correctness, novelty, peer review, or resolution of an external problem. Humans remain responsible for infrastructure changes, exceptional moderation, appeals, rights issues, and governance. Unsupported clinical or hazardous material is outside the initial discipline scope.

## 2. Deployment and repository responsibilities

Use two active repositories, not one per discipline:

- `ORG/ORG.github.io`: the trusted Python platform package (`rp`; never name it `platform`, which shadows the standard library), JSON Schemas, policies, research profiles, reviewer adapters, importers, CLI, site templates, tests, pinned reusable workflows, operations documentation, and Pages deployment. It is both the trusted platform repository and the organisation website repository. No ordinary research contribution may change it.
- `ORG/research`: current accepted research source files, problem records, thin SHA-pinned workflow callers, contribution forms, trusted workspace instructions, migration manifests, and a separately protected `automation-ledger` branch. Contributor content is always untrusted, including after merging.

The existing `mehmetmars7/Erdosproblems-llm-hunter` stays a preserved legacy archive and compatibility site after a separately authorised cutover. It is not a permanently synchronised second contribution destination.

Stack: Python, JSON Schema, Jinja2, Pandoc with a restricted rendering profile, MathJax, Pagefind, and modest browser JavaScript. No custom server, database, microservices, general frontend framework, or contributor-code execution in the MVP. Pin dependencies, action SHAs, reusable-workflow SHAs, and renderer images. Generated HTML, ZIPs, and PDFs never go in the authoring branch.

Suggested platform layout:

```text
ORG/ORG.github.io
├── rp/         schemas/ profiles/ policies/ intake/ validation/ screening/
│               publication/ exports/ migration/ cli/
├── site/       templates/ editorial/ assets/
├── tests/      unit/ fixtures/ stress/ security/
├── operations/ settings checklists, runbooks, restore drills
├── docs/       IMPLEMENTATION_SPEC.md, adr/
├── CLAUDE.md
└── .github/workflows/
```

## 3. Canonical storage and identity

Research authoring tree:

```text
research/main
  problems/<two-character-shard>/<problem-id>/
    problem.yaml
    statement.md | statement.tex
    contributions/<contribution-id>/
      contribution.yaml
      files/...
    reviews/<review-contribution-id>/
      contribution.yaml
      files/review.md
  browse/                       # generated, non-authoritative handle → folder indexes
  migration/<import-id>/mapping.jsonl
  .github/ISSUE_TEMPLATE/...
  .github/workflows/...         # trusted thin callers only
  AGENTS.md
  CLAUDE.md                     # imports the trusted AGENTS.md
  .devcontainer/...

research/automation-ledger
  identities/  revision-descriptors/  statement-revisions/  events/
  candidates/  decisions/  spend-reservations/  artifact-locations/
  publication-snapshots/
```

Use prefixed 128-bit UUID identifiers for new entities: `prb_` problem, `con_` contribution (including reviews), `rev_` revision, `stm_` statement revision, `art_` artifact, `evt_` event, `pub_` publication snapshot. Identifiers must not depend on model, filename, date, discipline, repository, or display order. Importers reuse a retained identity mapping on repeated runs.

Human-readable aliases such as `ERDOS-5`, `ECON-C73-1`, `MATH-12`, `ERDOS-5.2`, and `ERDOS-5.2.1` are permanently reserved by the publisher controller. Hierarchical aliases describe registration lineage, not an automatically renumbered current tree. Abandoned reservations leave gaps; aliases are never recycled. External scheme/source/identifier mappings are preserved with the allocation authority explicit. A local alias does not assert that an external catalogue recognises the record.

Keep one primary hierarchical parent, a cycle-free `subproblem_of` relation, and additional typed graph relationships. Reparenting changes relationships, not identity or aliases. Relationships never propagate solved status. A cross-problem contribution has one canonical home folder and several target relationships; reverse indexes show it under every target without duplicating source files.

Generate Markdown browse indexes mapping human handles to their GitHub folders, and put a source-folder link on every problem page. They are reproducible generated output included in managed publication PRs, never contributor-granted authority or a canonical registry.

The current main-branch file set is an authoring view of the latest accepted revision. It is not the historical record and may be newer than the latest published revision. Historical descriptors reference retained source commits, exact manifests, and immutable-by-policy packages. Never use `_v2.tex` or copied `v2/` directories as the revision system.

## 4. Data contracts

All records carry `schema_version`. Authoring uses safely parsed YAML; fingerprints use a specified canonical JSON representation plus sorted artifact manifests. Reject duplicate mapping keys, ambiguous scalar coercions, unsafe YAML tags, and unknown core fields. Optional namespaced extensions survive export/import; an unsupported required research profile fails compatibility explicitly.

### Problem and statement revision

`problem.yaml` contains `problem_id`, `statement_revision_id`, `expected_statement_predecessor`, `title`, `kind`, `disciplines[]`, `classifications`, `statement_artifact`, `external_ids[]`, `sources[]`, `relations[]`, `rights`, and optional `extensions`.

`kind` is `catalogued`, `literature`, `proposed`, `derived`, or `legacy_unclassified`. Source observations keep source authority, raw status, normalised status, source snapshot, observation date, and provenance. Ordinary submissions cannot manufacture catalogue authority or change trusted external source status. Changing the statement or its scientific interpretation creates a new statement revision.

### Contribution and authored revision

`contribution.yaml` is the authored document for one exact proposed or accepted revision. Required identity fields: `contribution_id`, `revision_id`, `expected_predecessor`, `type`, `home_problem_id`, `targets[]`. Scientific fields: `title`, `profiles[]`, `claim`, `attribution`, `model_uses[]`, `lineage[]`, `artifacts[]`, `rights`, `declarations`, `extensions`.

Initial types: `attempt`, `counterexample`, `correction`, `review`, `author_response`, `replication`, `legacy_record`. Review-specific fields are required only for review-like types. Profiles are distinct from disciplines: `mathematical_argument`, `computational_experiment`, and `review` are enough at launch; empirical/data profiles can stay minimal and accept unexecuted artifacts.

Each attempt target names `problem_id`, `statement_revision_id`, and target scope. A claim has `type`, `scope_statement`, assumptions/limitations where applicable, and an optional contributor-reported completion estimate. A percentage is never mandatory and never a confidence or correctness score.

Attribution distinguishes submitter, human research contributors, organisations, and model/tool uses. Human fields: stable platform person reference, GitHub numeric account ID where available, login at the event, declared roles, authorship-confirmation state. Model-use fields: provider, raw declared name, normalised family when justified, exact known API/model version or explicit `unknown`, role, settings when known, generation-date claim with precision, provenance evidence. Model identity is never inferred from a folder or conversation URL. `contribution_mode` is `human_only`, `ai_only`, or `human_ai`; even AI-only work has an accountable submitter.

Provenance levels, weakest to strongest: `declared`, `linked` (share link the owner can delete), `archived` (stored transcript with hash), `archived_attested` (contributor-run workflow signed with GitHub artifact attestations; proves only that the contributor's workflow produced the files), `platform_generated` (produced by platform-controlled infrastructure).

Authorised editors and ownership changes live in the ledger, not in author-editable YAML. A correction by an authorised editor is a new revision of the same contribution. An independent attempt or extension gets a new contribution ID; a derivative links to the exact source revision. Outsiders submit reviews/corrections and never overwrite another contribution.

### Trusted revision descriptor

The controller writes `revision_id`, `contribution_id`, `predecessor`, accepted sequence label, candidate fingerprint, canonical scientific-metadata digest, artifact manifest, target statement revisions, intake references, candidate head SHA, merged source commit, policy/rubric/context versions, authorised actor evidence, and linked events. Descriptors are written only after referenced commits exist.

Define two separate values:

```text
Scientific fingerprint S = hash(canonical scientific metadata + attribution + target statement
                                revisions + dependency references + sorted artifact manifest)
Authorization binding K  = repository + candidate PR + head SHA + base SHA + S + expected predecessor
                           + policy version + rubric version + review-context digest + editor state
```

Revisions sharing an expected predecessor cannot both advance the accepted head; the second is reconciled, reassessed, or made a separate derivative. A base change may reuse AI analysis only if S and the review-context digest are unchanged; deterministic checks always rerun.

### Reviews, events, artifacts, snapshots

Reviews are versioned contributions targeting an exact contribution revision and optionally a claim/location. Record finding, checked scope, evidence, reviewer attribution, conflicts, AI assistance, and response/retraction relations. Never transfer a favourable R1 review to R2.

Events have `event_id`, `type`, actor, targets, `occurred_at`, `recorded_at`, time source, precision, evidence, policy version, and idempotency key. Keep submitted, accepted, merged, published, revised, activity, and claimed generation dates separate. System timestamps are UTC; date-only legacy claims stay date-only.

Artifacts have ID/version, digest, byte count, media type, role, logical path, rights, provenance, availability, and storage locations: `in_repository`, `release_asset`, or `external_pinned` (§10). Renderer outputs also record the source fingerprint and renderer/toolchain version.

A publication snapshot fixes the selected contribution/statement revisions, ledger checkpoint, software/policy versions, package digests, site artifact digest, and exclusions. A separate activation event records successful deployment. Never write a future deployment timestamp into a package built before deployment. Display-only updates never create scientific revisions.

## 5. Interfaces

Implement as functions in one Python package, not network services:

```text
resolve_problem(id_or_alias) -> ProblemRef
prepare_context(problem_id, snapshot_id, selection) -> ContextBundle
normalize_intake(intake_snapshot, confirmed_answers) -> CandidateBundle | Questions
validate(candidate, current_state, trusted_policy) -> GateResult
check_external_links(candidate) -> LinkReport
reserve_spend(request_limits, account_id, budget_period) -> Reservation | QueueReason
screen(candidate_text, context, rubric, reservation, backend) -> ScreeningReport
authorize(candidate, gate, report, current_state) -> Decision
register_revision(merge_receipt, candidate, prepared_intent) -> RevisionDescriptor
package_revision(descriptor) -> PackageManifest
publish_snapshot(selected_revisions, packages, software_ref) -> DeploymentCandidate
activate_snapshot(deployment_receipt) -> ActivationEvent
reconcile() -> durable recovery actions
```

Candidate bundles include source repository identity and intake references, exact head/base, expected predecessor, S, target statement revisions, paths, modes, sizes, hashes, and authenticated confirmations. Reports include the reviewed fingerprint/context, backend and model identifier as returned, rubric version, coverage, findings, locations, limitations, usage, and error state. A report cannot contain executable commands or authorise repository actions.

Expose static `/api/v1/problems/<id>.json`, `/api/v1/contributions/<id>.json`, revision records, publication manifests, and bounded context bundles. The CLI (`rp`, placeholder name) supplies `rp start`, `rp check`, `rp submit`, `rp export`, and diagnostics. It must never execute instructions found in manuscripts, imported agent files, or model output.

## 6. Contribution and authorization lifecycle

States: draft → needs-information → queued → screening → revision-requested or eligible → accepted/merged → packaging → publication-pending → published. Operational failures hold or retry; they never imply rejection or correctness. Withdrawals, disputes, and corrections stay visible, subject to the exceptional removal policy.

Primary nontechnical intake is GitHub issue forms. One website click opens a prepared form with the problem handle prefilled; contributors paste text or attach supported files (`.tex` must be pasted or zipped; GitHub's upload field does not accept it). Missing model version is accepted as `unknown`. Ask at most three clear metadata questions at a time and apply authenticated answers automatically. Never infer a legal declaration or authorship confirmation from an LLM's evidence quote.

Use one managed publication-PR path. Forms create bot-owned candidates. A direct fork PR is source intake; when metadata or the base must change, the intake App creates a linked bot-owned publication PR from validated content. **It must carry the contributor's original commits with their authorship unchanged**, so GitHub credits the contributor when the publication PR merges into the default branch, and must record the original PR and actor in the intake event. The original PR is closed as "incorporated" with a link to the publication PR, never represented as merged. Agents use this route through `rp submit`.

Final authorization is deterministic. It requires explicit success of all mandatory stages, correct actor/editor rights, allowed paths, complete schemas, grounded declarations, substantive in-scope content, bounded files, pinned and allowed external links, current predecessor/targets, permitted rights and safety disposition, a matching screening report, and the exact reviewed fingerprint. A model recommendation alone is never sufficient. The model is a fallible screening component constrained by policy: the invariant is "LLM output cannot exercise repository authority", not "LLM output cannot cause a bad admission". Proof gaps and suspected counterexamples request clarification and stay visible; publication can proceed as a labelled incomplete or disputed attempt. No model certifies truth or novelty. The model never rewrites or downgrades the author's claim; it asks, and confirmed changes create a new candidate.

A serialized publisher controller revalidates the current candidate and merges through the API with the expected head SHA. Do not leave native auto-merge enabled. Require current-base validation and up-to-date publication branches.

## 7. Credentials and trust boundaries

Two separately registered GitHub Apps:

- Intake App: research-repository branch/PR/comment functions only; not the final required-check identity; no protected-main or ledger bypass.
- Publisher App: final required-check issuer (`rp/authorize`) and controlled merge/ledger writer. Its private key is released only to the trusted controller, never to intake, extraction, AI screening, rendering, or contributor code. A private key can mint tokens with all of the App's permissions, so short-lived tokens do not make its holder low-privilege.

The screening job has the AI-provider credential but no repository-write or merge credential and no tools; its report is passed as an artifact that privileged consumers verify by origin, run, revision, schema, and digest. Extraction/rendering has no provider or publisher secrets and no unrestricted network.

Use protected default-branch workflow definitions and SHA-pinned reusable workflows. No required path may depend on approval-gated fork `pull_request` runs. With `pull_request_target`, never check out or run PR code, and bind checks explicitly to the PR head. Dispatch-driven controllers create an explicit publisher-App check.

Rulesets: one restricts `main` updates to the publisher's operational path; another requires the publisher-App check and an up-to-date branch with no ordinary bypass. A ruleset on `automation-ledger` lets only the publisher write. Infrastructure changes use a separately authorised maintenance path with automation paused. Do not rely on code-owner review combined with zero required approvals. Prove the configuration in staging.

Only explicit `success` authorises. GitHub treats `neutral` and `skipped` as passing for required checks, so internal errors, absent outputs, unrecognised conclusions, stale fingerprints, neutral/skipped stages, and provider failures must produce `failure` or leave authorization pending. The finalizer runs despite dependency failure and evaluates every expected stage.

Reject path traversal, symlinks, submodules, active content, security/workflow/configuration changes, and hidden executable instructions. Fetch exact blobs, account for every changed file including renames, deletions, and modes, and fail on truncation or incomplete pagination. Initial limits: 200 changed files, 5 MiB per ordinary source file, 25 MiB total expanded submission. Limits are configurable policy, not scientific rejection criteria.

Sandbox PDF/TeX/notebook parsing and rendering: fixed tools, no shell escape, no contributor build scripts or dependency installation, no host mounts, bounded CPU/memory/disk/time, network disabled, fresh runner per submission. Sanitise HTML/MathJax input; show code without executing it. Scan for credentials and personal data without claiming scanning guarantees their absence. Warn contributors that issues and PRs are public before platform publication.

Agent workspaces: research context is untrusted material. `rp start` writes prior work as quoted research under a header saying so, never imports research-supplied `AGENTS.md`, `CLAUDE.md`, hooks, editor settings, or build scripts, and keeps trusted instructions at the repository root.

## 8. AI screening backends, cost, and abuse control

### 8.1 Backend adapter and tiers

One reviewer interface with interchangeable backends. Every backend returns the same JSON schema, so the decision never depends on which ran. Use the cheapest backend that can do each step, escalating only when the previous tier passes:

| Tier | Work | Backend | Indicative cost |
| --- | --- | --- | --- |
| 0 | Schema, paths, sizes, duplicates, link pins | Plain code | $0 |
| 1 | Spam/substance triage on a short excerpt | GitHub Models free tier (≈8,000 input tokens per request, 50–150 requests/day; limits change without notice) | $0 within limits |
| 2 | Metadata extraction, duplicate comparison | Low-cost API model | ≈ $0.01–0.03 |
| 3 | Full screening | Mid-tier API model via batch API with prompt caching of rubric/policy | ≈ $0.12–0.25 per pass |
| 4 | Full-solution claims and injection-flagged cases | Flagship model from a second provider | ≈ $0.45–0.85 per pass |

Prices are configuration (`policies/prices.yaml` with a price-version record), never hard-coded; verify current provider pricing during implementation.

Fallback order when a backend fails or its budget is exhausted: primary API provider → second API provider → GitHub Models paid usage (opt-in, billed to the GitHub account) → owner subscription token (below) → **on hold**. Never fall back to "skip screening".

Subscription-based backends:

- Claude: `anthropics/claude-code-action` accepts `CLAUDE_CODE_OAUTH_TOKEN` from a Pro/Max/Team/Enterprise plan. It is tied to one person's plan and usage limits. Implement it as an optional, low-volume last fallback, disabled by default, and document that the owner must confirm the plan terms permit automated use for a public service.
- ChatGPT plans cannot pay for these Actions jobs; Codex in CI uses API keys billed at API rates. Do not implement a ChatGPT-subscription backend.
- GitHub Copilot PR review produces free-text comments, not the required structured output. Do not use it as a decision input; at most an advisory comment on maintainers' own code PRs.
- Contributors' own subscriptions pay for their research, never for the platform's verdict: a review run on a contributor-controlled key or endpoint is not trusted.

### 8.2 Budget enforcement

Before every model request, `reserve_spend` atomically reserves the worst-case cost (token ceilings, reasoning/output limits, retries, fallbacks) against global and per-account budgets in the ledger, using a conditional (non-force) ref update with retry. Concurrent jobs therefore cannot all see the same remaining budget. Settle actual usage afterwards; requests with uncertain billing outcomes keep a conservative reservation. Provider console limits and prepaid credit are secondary safeguards, not instantaneous guarantees. Default budget: USD 100/month, owner-approved. No retroactive screening of legacy material.

### 8.3 Stopping credit-draining submissions without routine human work

1. Nothing reaches a paid model until Tier 0, needs-information, and Tier 1 pass.
2. Drafts are free; screening starts only when marked ready or on `/review`.
3. Identical or near-identical content is never paid for twice: reports are cached by S.
4. Automatic trust tiers from GitHub signals: accounts under 30 days old or without a merged contribution get 1 paid screening per day and 3 per month; contributors with merged work get 5 per day; clean repeat contributors more. All values are policy configuration.
5. All new accounts share one small daily pool (default USD 3). A swarm of fresh accounts drains only that pool for that day; established contributors keep their budgets.
6. Hard caps: 5 paid rounds per submission, per-call token ceilings, size limits; re-reviews analyse the diff plus the prior report.
7. Automatic penalties: a rejection for spam or reviewer manipulation sets the account's quota to zero for 30 days; a second makes it permanent pending appeal; clear abuse triggers an automatic organisation-level block through the API.
8. Spend-rate tripwire: if hourly spend exceeds a configured multiple of the trailing average, new-account screening pauses automatically and those submissions queue; established contributors are unaffected.
9. Outer walls: provider hard limits and prepaid credit, the monthly ledger budget, and a `SCREENING_ENABLED` kill switch.

Human effort is limited to appeals and reviewing the auto-block list.

## 9. Durable controller and crash recovery

The ledger uses append-only events and non-force conditional branch updates; derived current state is rebuildable. One controller serialises protected transitions. Every event handler and scheduled reconciliation scans durable unfinished work instead of assuming one Actions run per submission. Workflow concurrency is not the queue: by default GitHub cancels older pending runs, and `queue: max` holds only 100. Preserve prepared intents before external writes and key transitions by stable idempotency keys.

Recover from a crash after merge but before registration, after package upload but before manifest registration, and after deployment but before activation recording. Reconcile against authenticated merge/deployment evidence and exact hashes. Never invent timestamps or repeat AI screening because packaging failed. Keep the last good published snapshot. Serialise activation; a stale snapshot never replaces a newer one. Rollback is a separately recorded operation.

GitHub disables scheduled workflows in public repositories after 60 days without activity. Provide an external health check and document it in the runbook.

## 10. External links and linked artifacts

Executable and large artifacts are linked, never hosted: Lean/Coq/Isabelle sources, software projects, notebooks, model weights, and large datasets. This matches the legacy repository's existing Lean policy. The repository stores only TeX with `.bib`, Markdown, PDF, figures, and small non-executable data (CSV/JSON) within §7's limits.

Rules, enforced by `check_external_links` in Tier 0:

- Artifact links must point to hosts in `policies/external-hosts.yaml`: GitHub and Hugging Face by default; Zenodo and Software Heritage as archives.
- Links must be pinned: a full 40-character commit SHA for GitHub, a revision hash for Hugging Face, a versioned DOI for Zenodo, a SWHID for Software Heritage. Branch, tag, or "latest" links are rejected. The pin is part of S.
- Reference links (DOI, arXiv, publishers) may use other hosts but must be HTTPS. Reject URL shorteners, raw IP hosts, `javascript:`/`data:` schemes, and confusable Unicode domains.
- Pin verification runs in a job with no secrets, only through the GitHub and Hugging Face APIs, with size, time, and redirect limits. The AI reviewer never fetches URLs; its report states "linked artifact not examined".
- For Hugging Face links, read the file list through the Hub API and flag pickle-format weights and repositories requiring remote code.
- Nothing linked is fetched into the build, executed, embedded, or hot-linked. Render links with `rel="noopener noreferrer nofollow ugc"` and `referrerpolicy="no-referrer"`. Pages show a warning: external code or data, not run or checked by the platform; use an isolated environment.
- A weekly link check marks vanished targets `unavailable` without changing any scientific label. Exports list them as `external` or `unavailable`, never as included.
- Linked material is subject to the same safety and takedown policy as uploads; maintainers can disable a link and leave a tombstone.
- A "machine-checked" label requires a formal-check record from an isolated evidence workflow (deferred), never a contributor claim.

## 11. Website, downloads, and continuity

Canonical routes use opaque identities; permanent aliases resolve to them:

```text
/problems/<alias>/                         /contributions/<alias>/
/contributions/<alias>/<revision-label>/   /problems/<alias>/downloads/<snapshot>/
/p/<uuid>/  /c/<uuid>/                     permanent alias redirects
```

Citations default to the selected immutable revision. Problem pages aggregate actual human/model contributions with precise links and declared provenance, and show these independent axes: source status, claim, automated screening, community findings, machine checks, external publication (with peer-review evidence and whether it matches this revision; a DOI alone is not proof of peer review), and lifecycle. None changes another; nothing changes a problem's source status.

Build static Mathematics and Economics pages, paginated problem/attempt listings, scoped Pagefind search, contributor/model views, history, and accessible source fallbacks. Never load whole catalogues or manuscripts on the homepage (the legacy homepage loads about 111 MB of data bundles). Benchmark a 500-attempt/200-contributor/30-subproblem fixture. Targets: 200 KiB initial first-party page payload excluding optional MathJax and manuscripts; fail the build at 800 MiB of Pages output.

Every published revision gets an exact source package: manifest, README, attribution, rights, checksums, citation metadata. Preserve original artifacts unchanged. Generate PDFs only for supported profiles; failure never blocks source publication. Store ZIP/PDF assets in versioned GitHub Release assets (≤ 1,000 assets per release, each under 2 GiB), never on Pages or the authoring branch; never overwrite an asset. Quarterly archival snapshots may be immutable releases deposited in Zenodo. Mirror archival assets and Git/ledger history off the sole production account.

"Download all attempts" means the latest published revision of each directly linked attempt as of an explicit snapshot. Historical revisions, reviews, and subproblem descendants are explicit options. Include withdrawn/disputed status and critical reviews, and list every exclusion and external or unavailable artifact. Keep immutable revision packages separate from evolving review dossiers. Reuse revision packages and coalesce problem archives into named snapshots; never rebuild the whole collection on every change, and never assemble large archives in the browser.

## 12. Migration and acceptance

Audited input commit: `b1f633121074e16579fa7fd05314e5f504d29bae` in `mehmetmars7/Erdosproblems-llm-hunter`. Re-inventory later changes before cutover.

Preserve the original repository, history, paths, third-party notices, issue/review evidence, and source bytes. Keep a retained mapping from repository ID + path + source commit/blob to new identity and revision or legacy snapshot, with evidence and uncertainty. Distinguish statements, original attempts, reused writeups, external summaries (`top_problems/openai`), and supporting artifacts; not every TeX file is an attempt.

- Do not infer revision lineage from `_v2` or same-model folders; the Economics notes call `C73-1.tex` and `C73-1_v2.tex` separate attacks. Ambiguous cases get `lineage_status: unknown` and a possible relation.
- Do not infer human-only work from `Human_Contribution`; `30007097.tex` discloses Codex assistance.
- Preserve `FIRST_POSTED` as a declaration and Git `%aI` dates as Git author dates; neither becomes `published_at`.
- Historical reviews: recover earlier file states from history (the converter overwrote per-problem files); distinguish labeller, issue author, and reviewer; unscoped reviews stay problem-level legacy records.
- Keep Erdős, UnsolvedMath (including 838 `LOCAL-` records), MathOverflow, and Economics identifiers and authorities distinct. Economics JEL/initial-rank IDs are permanent; current ranks and reused OP IDs are not identity.
- Retire inferred "solved" fallbacks without erasing their historical values.
- Do not apply a new blanket licence to legacy material; keep source-specific terms and use link-only records where redistribution is unclear.
- Keep legacy site paths, query-string mappings (`problem.html?type=…&id=…`), source URLs, and download links working; unknown mappings land on a useful legacy page or search.

Cut over once; the old repository stays the archive. Rollback restores publication pointers and disables automation without recycling IDs or rewriting history.

### Milestones (each starts in plan mode and ends with owner sign-off)

1. Staging org, schemas, identity rules, event model, threat model, deterministic fixtures.
2. Idempotent migration, revision packages, two-discipline site, citations, dates, legacy URL map.
3. Forms, CLI/agent context, clarification, managed publication PRs, proposed problems/subproblems, revision-targeted reviews, external-link checks.
4. Gate, isolated screening with backend tiers, spend reservations and abuse controls, App permissions, deterministic decision — in shadow mode.
5. Serialised merge/register/package/deploy controller with failure injection and reconciliation.
6. Security and usability acceptance, then separately authorised production cutover.

### Acceptance tests before autonomous production publication

- A fresh external contributor submits through an issue, answers missing metadata without writing YAML, and publishes without human approval.
- Agent/local and fork-PR intake preserve attribution, commit authorship, and original references through managed publication PRs.
- Fifty concurrent sibling proposals obtain distinct permanent aliases; dropped or repeated workflow runs lose no accepted work.
- Two concurrent revisions with the same predecessor cannot silently overwrite each other.
- Changing metadata, target statement, source bytes, external-link pins, or review context invalidates stale authorization.
- Workflow changes, malicious paths, hostile archives, forged reports, prompt injection, skipped jobs, and neutral checks cannot gain merge or secret access.
- Unpinned links, disallowed hosts, shortener and confusable-domain links are rejected; Hugging Face pickle weights are flagged.
- A later serious error yields a visible revision-specific objection; old packages and citations survive; favourable reviews do not transfer.
- A problem snapshot identifies all selected versions, rights, exclusions, and checksum-valid assets; export/import works in a clean instance.
- Budget exhaustion queues work before spending beyond reserved limits; retries and fallbacks obey the same accounting; a 100-new-account swarm spends no more than the newcomer pool; the tripwire pauses only new-account screening.
- Fault injection at every external side effect recovers without duplicate identities, fabricated dates, or unnecessary AI calls.
- A second maintainer restores Git, ledger, packages, identity mappings, and site from backups, rotates credentials, and suspends publication.

Defer: custom OAuth forms, non-GitHub accounts, ORCID verification, per-attempt DOIs, formal-proof execution, notifications, reputation, hosted search, alternative databases, RO-Crate export, and additional disciplines. Provider adapters and the export contract are required now; implementing alternative infrastructure is not.

## 13. Owner decisions required before milestone 1

| Decision | Default if not specified |
| --- | --- |
| Organisation name and custom domain | Discipline-neutral org; domain owned by the org |
| Licence for new contributions | CC BY 4.0 for manuscripts; Apache-2.0 for software; inherited terms kept |
| AI budget and payer | USD 100/month cap; newcomer pool USD 3/day |
| Primary and second AI providers | Choose after shadow-mode benchmark |
| Whether to enable the subscription-token fallback | Disabled |
| Second organisation owner and appeals contact | Must be named before auto-publication |
| Allowed external hosts | GitHub, Hugging Face, Zenodo, Software Heritage |
| Analytics | No third-party trackers |

---

# Part II — Product requirements

Part I defines the machinery. Part II defines what contributors and readers experience. Both are binding; where they seem to conflict, ask the owner.

## 14. Disciplines and extensibility

- Each discipline is configuration, not code: `policies/disciplines/<slug>.yaml` sets name, URL slug, alias prefix (`MATH`, `ECON`, later `CS`, `PHYS`, `BIO`), classification scheme (MSC 2020, JEL, ACM CCS, PACS, …), enabled research profiles, accepted formats, a rubric addendum for screening, one optional disclaimer sentence, stewards, and status (`planned` | `pilot` | `active`).
- Launch with Mathematics and Economics `active`. Computer Science and Mathematical Physics problems already in the legacy UnsolvedMath catalogue (17 categories) are shown as secondary disciplines of those problems. Other disciplines appear on the homepage as `planned`, with a link for proposing problems.
- Adding a discipline must need only a config file, a classification vocabulary, and tests — no change to core code. Add a test that enables a dummy discipline end to end.
- A problem can have one primary and several secondary disciplines; its URL never contains the discipline.
- Biology and medicine stay `planned` until a named steward, ethics fields (approvals, data provenance), and a biosafety/clinical-claims screening category exist; until then such submissions go to on hold.

## 15. Problems, proposals, and subproblems

- Problem kinds (§4): `catalogued` (imported from an external authority), `literature` (cited open problem added by a contributor), `proposed` (new conjecture or question), `derived` (subproblem or variant of an existing problem), `legacy_unclassified`.
- Default catalogue views and open-problem counts show only `catalogued` and `literature`. `proposed` and `derived` appear in a separate "Proposed questions" view with the banner: "Proposed by a contributor. Not established as open or novel."
- Admission checks for problems:
  - All: well-posed statement, definitions, discipline and classification, proposer attribution, AI involvement, rights.
  - `literature`: citation resolves (DOI, arXiv, ISBN, or stable URL) plus a quote or locator for the statement; displayed as "citation not independently checked".
  - `proposed`: motivation, relation to known problems, elementary/boundary checks, literature/duplicate search performed, explicit novelty disclaimer.
  - `derived`: parent exists; nature declared (`restriction`, `special_case`, `step`, `reformulation`, `generalisation`); must not edit the parent; must state that it does not change the parent's status.
- Duplicate screening: compare the new statement with existing statements in the same discipline (embeddings or text similarity, Tier 2), then screen the top 5 candidates. Never auto-reject a likely duplicate; ask the contributor to explain the difference or link it as `variant_of` / `duplicate_of`.
- Relation types: `subproblem_of` (tree; one primary parent), `generalises`, `implies`, `implied_by`, `equivalent_to` (claimed), `variant_of`, `related`, `duplicate_of`, `promoted_from`. No relation propagates status. A curator may record, as a separate attributed event with evidence, that an established equivalence settles a parent.
- Promotion: a subproblem that becomes independent keeps its alias (e.g. `ERDOS-5.2`) and gains `promoted_from`; its page explains the history. URLs never change.
- `source_status` changes only via catalogue sync or a curator change set citing an authoritative source. Lifecycle for proposed problems: `proposed` → `literature` (curator with citation), `duplicate_of`, or `retired` (ill-posed, with reason).

## 16. Submission rules visible to contributors

### 16.1 Publication threshold (policy `policy/1`, versioned)

| Blocking — must be fixed | Non-blocking — published as screening notes |
| --- | --- |
| Schema, path, size, format, or link-pin failure | Suspected gaps or unjustified steps |
| Wrong or unrelated target problem | Possible counterexamples |
| Claim label broader than the stated scope (bot proposes a corrected label; contributor confirms) | Unclear notation, missing definitions |
| Missing disclosure: contribution mode, model names or explicit `unknown`, human roles, rights declaration | Missing literature or prior work |
| No substantive content (empty, restatement, incoherent) | Reproducibility gaps |
| Unattributed copying or licence violation | Questionable but resolving references |
| Credentials or personal data | Weak completion-estimate justification |
| Text addressed to the reviewer that tries to steer it | |
| References that cannot be resolved, until each is fixed or explicitly confirmed by the contributor (a network failure is not evidence of fabrication) | |
| Safety category (dual-use, clinical directives, sensitive data) → on hold, not revision | |

"The model could not verify this" is never a blocking reason; "the model found no error" is never shown as evidence of correctness.

### 16.2 Metadata clarification

1. Extract from form fields, any `contribution.yaml`, and (Tier 2) the manuscript.
2. Every model-proposed value must carry a verbatim quote from contributor-written text; code checks the quote exists; ungrounded values are discarded.
3. Inherit problem, discipline, and classification from the page that launched the form.
4. Required before publication: claim type and target scope, model names (version may be `unknown`), human roles, contribution mode, rights declaration. Everything else is optional.
5. Ask at most 3 numbered questions with suggested defaults; contributors reply in plain words.
6. Show "Recorded as: …" with the quote; the intake App commits the YAML to the bot-owned candidate.
7. Reminders at 7 and 21 days; closed-stale at 30 days; `/reopen` restores it.

### 16.3 Comment commands

Matched by exact pattern on the first line, rate-limited (10 per user per hour), ignored on closed items, and acted on by the intake App only:

| Command | Who | Effect |
| --- | --- | --- |
| `/review` | Author, maintainers | Leave draft, start screening |
| `/recheck` | Author, maintainers | Re-screen after a reply; counts toward the round limit |
| `/accept-label <type>` | Author | Accept the proposed corrected claim label |
| `/confirm-authorship` | Each listed human co-author | Sets their confirmation to `confirmed` (co-authors listed by someone else show "listed by submitter" until then) |
| `/withdraw`, `/reopen` | Author, maintainers | Withdraw or reopen |
| `/appeal <reason>` | Author | Moves to on hold for a maintainer; the only human step, optional |

After 5 rounds, if only non-blocking notes remain, the author may choose "publish with unresolved screening notes"; otherwise the submission goes to the appeal queue.

### 16.4 Accepted formats

Stored: TeX with `.bib`, Markdown with maths, PDF (text extracted for screening and search; source encouraged), figures, small CSV/JSON. Linked only (§10): Lean/Coq/Isabelle, code, notebooks, models, large datasets. Issue forms accept paste or upload of `.pdf`, `.zip`, `.txt`, `.csv`, `.json`, images.

## 17. Community reviews and disputes

- Anyone with a GitHub account can review a specific contribution revision via the review form or `rp review`. Fields: target revision, finding (`supports`, `error_found`, `gap_found`, `counterexample`, `known_result`, `reproduced`, `not_reproduced`, `reference_suggestion`, `comment`), scope checked, location, evidence, AI assistance, conflicts of interest.
- A listed author's review is recorded as `author_response`. Reviews are counted by finding and shown with scope, never as votes or a score.
- Screening for reviews: on topic, specific, no harassment or personal attacks; reviews go through the same quotas and pipeline.
- A specific objection (`error_found`, `gap_found`, `counterexample`) marks that revision **Disputed** and notifies the authors. It resolves when the objector closes it, or when a later revision addresses it and any reviewer marks it resolved; an inactive objector cannot block forever — after 90 days with an author response and no objector reply, it shows "Response given; objector has not replied". Nothing is deleted; the platform never rules on who is right.
- Attribution disputes and corrections use a correction form; they create a linked record, notify listed people, and resolve by a new revision from the submitter or, exceptionally, a maintainer action.
- Abuse controls: code of conduct; rate limits; automatic penalties (§8.3); organisation-level blocking; maintainers can hide a review behind a tombstone with a reason.

## 18. Scientific transparency and disclaimers

The platform accelerates open research; it does not replace journals, conferences, or peer review. State this, in plain words, on:

- **Homepage and About**: an open workspace and archive of attempts, many AI-generated or AI-assisted; AI output can contain errors, invalid proofs, invented references, and false claims; passing automated screening does not establish correctness, novelty, or validity; scrutiny, reproduction, and independent validation are encouraged; useful work should be developed into papers for proper peer review; respect credit, citation, licences, and third-party rights.
- **Every page footer**: one line linking to the status policy.
- **Contribution and revision pages**: one banner chosen from the revision's axes, e.g. "Unverified AI-assisted attempt. Automated screening checks form, honesty and scope — not correctness." A full-solution claim shows "Unverified claim of a full solution" next to the source status, e.g. "Status at erdosproblems.com: open".
- **Contribute pages**: five bullets on credit, citation, licences, third-party rights, and that submissions are public immediately.
- **Discipline sentence** (§14), e.g. biology: "Not peer reviewed; not medical advice."
- **Policy pages**: status and evidence axes (§11), review and screening policy, AI attribution and provenance, community guidelines and code of conduct, licences and third-party notices, privacy, takedown.

Discipline risks to encode in rubric addenda: mathematics — confident false proofs, statement drift; economics — results depending on unavailable data (data-availability field); computer science — unreproducible benchmarks (code shown, never run); physics — unsupported fringe claims (substance check); biology/medicine — clinical claims, personal data, dual use (not launched).

## 19. Website information architecture

Global navigation: Disciplines ▾ · Search · Activity · Contribute · About · GitHub. Breadcrumbs show discipline paths (Mathematics › Erdős problems › ERDOS-5).

| Page | URL |
| --- | --- |
| Home | `/` |
| Discipline home / catalogue / proposed / source collection / topic | `/mathematics/`, `/mathematics/problems/`, `/mathematics/proposed/`, `/mathematics/sources/erdos/`, `/mathematics/topics/<slug>/` |
| Problem, subproblem | `/problems/ERDOS-5/`, `/problems/ERDOS-5.2/` |
| Contribution, revision | `/contributions/ERDOS-5-A4/`, `/contributions/ERDOS-5-A4/r2/` |
| Review | `/contributions/ERDOS-5-R1/` (also shown on the reviewed revision) |
| Downloads | `/problems/ERDOS-5/downloads/<snapshot>/` |
| Person, model | `/people/<login>/`, `/models/<provider>/<model>/` |
| Search, activity | `/search/`, `/activity/` |
| Contribute guides | `/contribute/`, `/contribute/attempt/`, `/contribute/problem/`, `/contribute/review/`, `/contribute/agents/` |
| Policies, About | `/policies/…`, `/about/` |
| API | `/api/v1/…` |
| Legacy | Redirect stubs for `/Erdosproblems-llm-hunter/…` paths served by the legacy repository |

Page components:

- **Home**: mission with the AI caveat; search; discipline tiles with counts; recently active problems; recent contributions; "contribute in three steps"; links to policies and GitHub.
- **Discipline home**: overview; classification tree; search and filters; catalogue; recent activity; proposed questions; contribute buttons.
- **Problem page**: alias, title, kind badge, disciplines, topics, external IDs; status panel with three parts (source status with authority and date · claims on this platform · reviews and evidence) and the line "Claims here do not change the source status"; statement, source, licence; context and known results; paginated contribution cards (alias, title, claim, human/AI badge, models, people, axes, last activity; sortable and filterable); subproblem tree and related problems; contributors and models, each linked to their specific contributions; Contribute panel; history; source-folder link.
- **Contribution/revision page**: banner; claim (type, target, scope, optional estimate); attribution (submitter, humans with roles and confirmation, models with version, settings, provenance level); axes; rendered manuscript with contents and source fallback; downloads (§11); external artifacts with warnings; reviews and responses; revision history with compare links; originating PR/issue; "Cite this revision" (BibTeX, CSL-JSON).
- **Person and model pages**: every contribution and review linked to them.

Search and discovery (Pagefind filters plus per-discipline compact JSON facets): full text across disciplines; filters for discipline, topic, source, source status, kind, claim type, activity; "no attempts yet"; "promising partial results" defined objectively (partial result with at least one `supports` review or a formal check, and no open objection); recently submitted; review requested or disputed; by person; by model; related and subproblems. Revisit hosted search only on measured limits.

Rendering: Pandoc to HTML at build time, cached by fingerprint, MathJax only on pages with maths, source shown with a notice when conversion fails; Markdown with raw HTML disabled; notebooks are linked (§10); code highlighted at build time. Accessibility target WCAG 2.2 AA (semantic HTML, keyboard navigation, MathJax assistive MathML, no meaning by colour alone). No third-party trackers.

## 20. Contribution entry points

Every problem page has buttons — Submit an attempt, Propose a subproblem, Review a contribution, Improve this contribution, Propose a new problem — each opening a Contribute panel with four tabs:

1. **No setup**: opens the matching issue form with alias, action, and target revision prefilled via URL query parameters (keep URLs short; GitHub returns 414 for overlong ones).
2. **Chat assistant**: "Copy research prompt" copies a self-contained prompt (statement, sources, prior claims, open objections, honesty rules, output template) for ChatGPT, Claude, Gemini, or a local model; a link returns to the form to paste the result. Do not rely on undocumented prompt-prefill URLs.
3. **Coding agent**: Open in Codespaces (`https://codespaces.new/ORG/research?quickstart=1`, with a visible `rp start <alias>` command because the link alone does not load the problem); Codex desktop (`codex://threads/new?prompt=…&originUrl=…`); Claude Code (`claude-cli://open?repo=ORG/research&q=…`, prompt ≤ 5,000 characters, needs a local clone Claude Code has seen; GitHub-rendered Markdown strips these links, the website can show them); plus copyable commands for any terminal agent (Codex CLI, Claude Code, Gemini CLI). Codespaces usage is billed to the contributor's own quota.
4. **Git**: fork-and-PR instructions with `rp new attempt <alias>`.

Agent kit in `ORG/research`: `AGENTS.md` (workflow, formats, honesty rules: never invent versions, citations, or checks; label scope precisely; include the legacy prompts A–D adapted as "initial research" and "final self-audit" steps), `CLAUDE.md` importing it, `.gemini/settings.json` with `context.fileName: ["AGENTS.md"]`, and a dev container with `rp`, Pandoc, and TeX. Contributors with existing work upload it through the form or run `rp submit <files>`; the bot asks for missing metadata.

## 21. Operations and governance

- `operations/github-settings.md`: org 2FA required; base permission read; only owners install Apps; Actions limited to an allowlist of SHA-pinned actions; default `GITHUB_TOKEN` read-only; secret scanning and push protection on; Dependabot for Actions and Python; fork-PR approval "first-time contributors new to GitHub"; rulesets (§7); environments `intake`, `screening`, `publisher`, `pages` restricted to the default branch.
- Catalogue sync: scheduled job refreshes the Erdős status snapshot from `teorth/erdosproblems` (reuse the legacy `sync_erdos_status.py` logic) and records a source observation; failure keeps the last snapshot and warns.
- Runbooks: key rotation, kill switch, incident response, takedown, appeals, restore drill, onboarding a discipline steward.
- Governance: at least two organisation owners, documented funding and credential succession, code of conduct, appeals contact.
- Spend transparency: a public monthly summary generated from ledger spend records.

---

# Appendix — Traceability to the owner's original request

| Original request section | Covered in |
| --- | --- |
| 1. Role, objective, existing project | §0, §1, §12 |
| 2. Vision, homepage, discipline paths, unknown disciplines | §14, §19 |
| 3. Organisation and repository architecture | §2 |
| 4. Problem catalogue, problem pages, status separation, search | §4, §11, §15, §19 |
| 5. New problems, hierarchical subproblems, IDs, duplicates, promotion | §3, §15 |
| 6. Easy contribution: GitHub, Codex, Claude, VS Code/Codespaces, nontechnical | §6, §16.2, §20 |
| 7. Submission types and shared schema with discipline extensions | §4, §14, §16.4 |
| 8. Metadata collection and incomplete submissions | §6, §16.2 |
| 9. Human, AI, mixed attribution; aggregation; disputes | §4, §16.3, §17, §19 |
| 10. Automated AI review, auto-merge, state machine, security | §6, §7, §8, §9, §16.1 |
| 11. Voluntary community reviews | §17 |
| 12. Scientific transparency and disclaimers | §18 |
| 13. Model independence, authentication, costs | §8, §20 |
| 14. Website structure and UX | §11, §19 |
| 15. Scalability and maintainability | §9, §11, §21 |
| 16. Relationship with the existing repository | §12 |
| 17. Deliverables A–M | The architecture blueprint document; this spec implements its approved decisions |
| Later additions: links not hosting, affordable fallbacks, anti-abuse | §8, §10 |
| External review corrections (fail-closed checks, durable queue, App keys, migration fidelity) | §7, §9, §12 |
