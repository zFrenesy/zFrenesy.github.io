# ADR 0013: Intake, clarification and managed publication PRs

Status: Accepted, 2026-10-11 (milestone 3). The intake GitHub App is not created yet (owner decision); everything runs against a fake GitHub in tests and as a read-only dry run.

## Context

Milestone 3 (spec §12) covers:

- forms, CLI and agent context (done in ADR 0012);
- metadata clarification;
- managed publication PRs;
- proposed problems and subproblems;
- revision-targeted reviews;
- external-link checks.

Screening (M4) and merging (M5) are out of scope; submissions queue. The owner chose to build the intake logic now and create the App later.

## Decision

**Pure decision function.** `rp.intake.engine.process(snapshot, research, …)` reads an immutable snapshot of one issue or PR (`rp.intake.snapshot`) and the accepted research tree. It returns the new state and a list of actions. `rp.intake.publication.apply_plan` executes those actions through a `GitHubPort`. There are three implementations of the port:

- a fake backed by a real Git repository, for tests;
- `GhReadOnly`, for `rp intake dry-run`;
- `GhLive`, for the future App workflow.

**State in an App-authored comment.** The state lives in one comment, `<!-- rp-intake-state v1 {...} -->`, plus `intake: <status>` labels. It is trusted only when GitHub attributes the comment to the intake App ID; logins are never used for this. Each message carries a hidden key and is posted once. The state comment is written last, so a replay after a crash repeats nothing. This avoids a second store before the M5 ledger writer exists.

**Clarification (§16.2).** Values come only from three places:

- the author's form fields;
- the author's numbered replies to at most three questions, each with a suggested default;
- in M4, grounded model extraction. The `Extractor` protocol exists; M3 ships `NoExtractor`. `ground()` keeps only values whose quote is in contributor text, and never declarations.

Legal declarations come only from the author's own form checkboxes (`form_field`) or an interactive `rp submit` (`cli_confirmation`). Records are built with the same scaffolds as `rp new` and checked with the same `check_folder` as `rp check` before anything is written.

**Commands (§16.3).** Commands are matched as exact first lines and checked against numeric account IDs. The limit is 10 commands per user per hour. Commands on closed items are ignored, except `/reopen`. In M3:

- `/review` and `/recheck` count rounds; screening is M4;
- `/accept-label` waits for an M4 label proposal;
- reminders go out at 7 and 21 days, and items close as stale at 30 days.

**One publication path (§6).**

- **Forms.** A bot commit goes on `intake/issue-<n>`, and a publication PR is opened from it.
- **Fork PRs.** `intake/pr-<n>` points at the contributor's own head commit. Their commits, authors and committers are carried unchanged. The source PR is closed with "Incorporated into #M", never marked merged.
- **Additions only.** Only purely additive single-folder PRs are incorporated. Anything else gets an explanation and stays where it is.
- **No rebasing.** New folders cannot conflict, so M3 does not rebase.
- **Ledger.** The `contribution_submitted` event is not written. The publisher writes the ledger in M5.

**Person references.** Intake mints a new `per_` reference per submission, as `rp new` does. Mapping GitHub IDs to stable person references belongs to the ledger's identities (M5).

**External links (§10).**

- `rp/policies/external-hosts.yaml` (with schema) defines hosts, URL patterns that must contain the pin, shorteners and pickle suffixes.
- `check_external_links` is the offline Tier 0 check. It replaces the old host-only check in `rp check`.
- `verify_pins` runs in a separate `research-check.yml` job with no credentials, through the GitHub and Hugging Face APIs only, with time, size and redirect limits.
- **Confusable domains.** Rejected when they mix scripts, or when a non-Latin label consists only of Cyrillic or Greek letters that look Latin. Genuine words in those scripts pass.
- **Weekly sweep.** `rp links sweep` writes display-only availability that the site shows as "currently unavailable". Its schedule comes with the M5 health check.

**Problems (§15).** `rp.validation.problems` checks:

- the statement length;
- a classification. This is a warning for derived problems, because many imported parents lack one;
- the ISBN check digit;
- that the parent exists.

Tier 1 duplicate screening is a word-shingle Jaccard comparison within the discipline. It produces warnings in `rp check` and a question in intake; nothing is auto-rejected. Embeddings are M4.

**Reviews (§17).** `rp.reviews.summarise_reviews` computes per-revision counts by finding, Disputed, retraction, resolution by a reviewer of a later revision, and the 90-day "Response given; objector has not replied" rule. "Today" is the ledger checkpoint, so builds stay reproducible. The site shows a Disputed marker on contribution pages and rows, and "Subproblem of X (nature)" on derived problems.

## Consequences

- **Deployment needs owner approval:**
  - the intake App;
  - its key in the `intake` environment;
  - the caller workflow (`python -m rp.contribute.kit --with-intake APP_ID`);
  - adding `actions/create-github-app-token` to the org allowlist.

  See `operations/intake-app.md`.
- A fork PR's YAML can carry confirmed declarations written by any tool the contributor runs (threat model §5).
- Scheduled reconciliation covers labelled issues. Fork PRs are processed on their own events.
