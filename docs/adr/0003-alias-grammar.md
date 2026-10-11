# ADR 0003: Alias grammar, allocation authorities and contribution letters

Status: Accepted, 2026-10-11 (milestone 1 plan)

## Context

§3 asks for permanent human-readable aliases (`ERDOS-5`, `ECON-C73-1`, `MATH-12`, `ERDOS-5.2`, `ERDOS-5.2.1`) reserved by the publisher controller. Abandoned reservations must leave gaps and aliases must never be recycled. Hierarchical aliases describe registration lineage, and the allocation authority must be explicit. §19 adds contribution aliases (`ERDOS-5-A4`, `ERDOS-5-R1`) and revision labels (`r2`).

## Decision

**Grammar**

```text
problem       <PREFIX>-<local>             PREFIX = [A-Z][A-Z0-9]{1,9}
subproblem    <problem>.<k>[.<k>...]       k >= 1, at most 8 levels
contribution  <problem>-A<k> | -R<k>       k >= 1
revision      r<k>                         per contribution, assigned at acceptance
```

**Schemes.** Each scheme states its `allocation_authority`:

- `external_identifier` schemes copy an identifier assigned outside the platform. They are configured in `rp/policies/alias-namespaces.yaml`:
  - `ERDOS-<n>` copies the erdosproblems.com number.
  - `ECON-<JEL>-<rank>` copies the legacy Economics catalogue ID (JEL code plus initial rank).

  A local alias does not claim that the external catalogue recognises the record.
- `counter` schemes are minted by the platform (`we-solve`), one per discipline, from the discipline's `alias_prefix` (`MATH-<n>`, `ECON-<n>`, `CS-<n>`). A counter scheme for a `planned` discipline is disabled.
- Two schemes may share a prefix only if they cannot mint the same alias. The catalog refuses to load if an external scheme sharing a prefix with a counter scheme matches a plain number. This is why `ECON-12` (counter) and `ECON-C73-1` (legacy) can coexist.

**Counters.** Subproblem numbers come from a counter per parent (`sub:<parent>`). Contribution numbers come from a counter per home problem and letter (`con:<problem>:<A|R>`).

**Letters.** `R` is for `review` and `author_response`. `A` is for every other type: attempt, counterexample, correction, replication and legacy_record.

**Lifecycle.**

- A reservation moves from `reserved` to either `bound` or `abandoned`, and both are terminal.
- Counters only increase, so abandoned numbers are never reused, and an abandoned external alias is burned.
- Each entity has at most one live alias. A repeated request for the same entity and purpose returns the existing reservation. A different request for that entity is refused (`alias.entity_has_alias`).

**Resolution and reparenting.**

- Resolution is an exact lookup in the ledger-derived registry after upper-casing. It never guesses from the grammar.
- Reparenting changes relations only; `ERDOS-5.2` keeps its name even if its parent changes. Promotion adds `promoted_from` and keeps the alias.

**Deferred.** Namespaces for UnsolvedMath (including `LOCAL-` records), MathOverflow and `openai/math` are decided with the milestone 2 importer.

## Consequences

Every alias-allocating path goes through pure planners (`rp.identity.aliases`) and the ledger's compare-and-swap append (ADR 0006). The 50-thread stress test shows that concurrent sibling proposals get distinct, gap-free aliases.
