# ADR 0006: Event and time model, ledger store

Status: Accepted, 2026-10-11 (milestone 1 plan)

## Context

§4 and §9 require append-only events with actor, targets, occurrence and recording times, time source, precision, evidence, policy version and idempotency key. Submitted, accepted, merged, published, revised, activity and claimed dates must stay separate. Derived state must be rebuildable, and transitions must be serialised through non-force conditional updates keyed by stable idempotency keys.

## Decision

**Event fields.** `occurred_at` is a date claim `{value, precision}` with precision `year`, `month`, `day` or `instant`. `recorded_at` is always a UTC instant (`YYYY-MM-DDTHH:MM:SSZ`). `time_source` says where `occurred_at` came from:

- `system_clock`
- `github_api`
- `git_committer_date`
- `git_author_date`
- `contributor_declaration`
- `legacy_header`
- `catalogue_source`

Machine time sources must give instants. Declared dates must come from a declaration, a legacy header or a Git author date, so a `FIRST_POSTED` date-only claim stays date-only and never becomes a publication time.

**Event types (schema version 1).** Each type has a closed payload schema:

- `alias_reserved`, `alias_bound`, `alias_abandoned`
- `external_id_mapped`
- `statement_revised`
- `contribution_submitted`, `revision_accepted`, `revision_merged`
- `date_declared`, `activity_recorded`
- `snapshot_built`, `snapshot_activated`

Publication time is the activation event of the first snapshot that includes a revision. A snapshot record carries `built_at` only, never a deployment time. Later milestones add types such as spend reservations and objections, each with its own payload schema.

**Idempotency.**

- The key is `digest({I/1, type, scope, external_ref})`. It is derived from the request, not the outcome, so a repeated or resumed run produces the same key.
- Appending an event whose key exists with the same logical content (type, targets, payload) returns the recorded event and appends nothing.
- The same key with different content is treated by when it was planned:
  - Planned against an older head, it is a conflict: the caller re-plans.
  - Planned against the current head, it is an `IdempotencyConflict`.

**Store.**

- `LedgerStore.append(expected_head, events)` succeeds only if `expected_head` is current. This is compare-and-swap (CAS).
- The head is a hash chain over canonical events, starting from an `L/1` genesis digest.
- `MemoryLedger` implements this for tests and fixtures. The Git-backed store in milestone 5 implements the same protocol with a non-force `update-ref` or a conditional API update of `automation-ledger`.

**Derived state.** `rebuild(events)` replays the log. It raises `LedgerCorruption` if an event contradicts the state it applies to: a second reservation of an alias, a revision that does not extend the accepted head, or a snapshot activation that does not replace the active snapshot. `StateCache` applies only new events, for single-writer batch work.

**Operations.** `rp.ledger.operations` reads state, plans with pure functions, appends with CAS and retries on conflict. Domain refusals such as a stale predecessor or a taken alias are raised and never retried away.

## Consequences

Two revisions sharing a predecessor cannot both be accepted (stress-tested with 8 racing writers). A lost response after a successful write is recovered by rerunning, with no duplicate identity.

Second-precision `recorded_at` does not order events; ledger order does. Workflow concurrency is never relied on as a queue (§9).
