# ADR 0004: Canonical JSON, scientific fingerprint S and authorization binding K

Status: Accepted, 2026-10-11 (milestone 1 plan)

## Context

§4 requires a specified canonical JSON for fingerprints and defines two values: the scientific fingerprint S and the authorization binding K. Screening reports are cached by S (§8.3). Any change to metadata, the target statement, source bytes, external-link pins or the review context must invalidate a stale authorization (§12).

## Decision

**Canonical JSON v1** (`rp.canonical`) is the subset of RFC 8785 (JCS) that covers objects, arrays, strings, booleans, null and integers of magnitude at most 2^53 − 1.

- Floats are rejected, because their decimal form is the main source of JCS incompatibility. Decimals such as prices and model versions are strings.
- Keys are sorted by UTF-16 code units, and the output is UTF-8 with minimal separators.
- Strings are never Unicode-normalised.
- For this subset the bytes are identical to JCS, so any JCS library reproduces our digests.
- Digests are written `sha256:<64 hex>`.

**S** (`scientific_fingerprint`) is the digest of:

```text
{version: "S/1",
 metadata:   contribution.yaml minus identity fields, attribution, targets and lineage,
 attribution: {attribution, model_uses},
 target_statement_revisions: targets, sorted canonically,
 dependencies: lineage, sorted canonically,
 manifest:   sorted artifact manifest}
```

- The identity fields excluded from the metadata are `contribution_id`, `revision_id`, `expected_predecessor` and platform-assigned `artifact_id`s.
- The manifest has one entry per in-repository file (logical path, digest of exact bytes, size, Git mode) and one per external link (URL and pin).
- The manifest is built from exact blobs. Undeclared or missing files, symlinks, submodules and paths outside `files/` are rejected.
- The order of targets and lineage does not matter. The order of humans does, because author order is meaningful.

A proposed problem has an analogous `P/1` fingerprint over its metadata and statement bytes.

**K** (`authorization_binding`) is the digest of `{version: "K/1", repository, pull_request, head_sha, base_sha, scientific_fingerprint, expected_predecessor, policy_version, rubric_version, review_context_digest, editor_state_digest}`.

- Every input is validated. A missing or malformed input raises an error instead of producing a value (fail closed).
- `editor_state_digest` is `E/1` over the owner and the sorted set of editors read from the ledger, never from author YAML.

The version tags (`S/1`, `K/1`, `P/1`, `E/1`, `I/1` for idempotency keys, `L/1` for the ledger genesis) are part of each digest, so a future change of composition cannot collide with old values.

## Consequences

An identity-only change, such as resubmitting identical content as a new candidate, keeps S, so cached screening can be reused. A base-branch change alters K but not S. Deterministic checks always rerun. AI analysis may be reused only when S and the review context are unchanged (§4).
