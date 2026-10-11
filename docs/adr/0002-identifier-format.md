# ADR 0002: Identifier format

Status: Accepted, 2026-10-11 (milestone 1 plan)

## Context

§3 requires prefixed 128-bit UUID identifiers that do not depend on model, filename, date, discipline, repository or display order. It lists `prb_ con_ rev_ stm_ art_ evt_ pub_`. §4 also requires a "stable platform person reference" for human contributors but names no prefix.

## Decision

- An identifier is `<prefix>_<32 lowercase hex digits>`: a UUID version 4 written without hyphens, for example `prb_3f2a9c0e8b7d4e1fa6c5b4d3e2f1a0b9`. Validation checks the prefix, the version nibble (4) and the RFC 4122 variant.
- UUIDv7 is rejected because it embeds a timestamp, which would make identifiers date-dependent.
- `per_` is added for platform person references. A GitHub account can be renamed, and some people (legacy authors, co-authors without accounts) have none, so the GitHub numeric ID and the login at the time of an event are stored alongside `per_`, not instead of it.
- Production identifiers come from `secrets.token_bytes`. `SeededIdSource` exists only for deterministic fixtures and tests.
- Problem folders are sharded by the first two hex digits of the UUID (`problems/3f/prb_3f2a…/`), giving 256 evenly filled shards.
- The JSON Schemas and `rp.identity.ids.id_pattern` share one regular expression. A test keeps them identical.

## Consequences

Identifiers are opaque. Human-facing names are aliases (ADR 0003). Milestone 2 decides whether `/p/<uuid>/` routes use the 32-hex form or the full prefixed identifier, and records that choice in an ADR.
