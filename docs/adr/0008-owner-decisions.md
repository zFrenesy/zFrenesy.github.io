# ADR 0008: Owner decisions for milestone 1 (spec §13)

Status: Accepted, 2026-10-11 (confirmed by the owner)

## Decision

| Decision | Value | Where |
| --- | --- | --- |
| Organisation | `we-solve` | `rp/policies/platform.yaml` |
| Repositories | `we-solve/we-solve.github.io` (platform and website), `we-solve/research` | `platform.yaml` |
| Site | `https://we-solve.github.io/`, with discipline sections `/mathematics/`, `/economics/`, `/computer-science/` on the same site | `platform.yaml` |
| Computer Science | `active` at launch, alias prefix `CS`, ACM CCS 2012 classification | `rp/policies/disciplines/computer-science.yaml` |
| Staging organisation | `we-solve-staging`, created by the owner. Claude Code configures it with the owner's `gh` login (commands shown first) when milestone 2 needs it. Apps, secrets and API keys, and billing or spend limits still need the owner's approval. Production and the legacy repository are never touched without asking. This overrides spec §0 for staging. | `platform.yaml`, `operations/staging-org.md`, CLAUDE.md |
| Licences for new work | CC BY 4.0 for manuscripts, Apache-2.0 for software; inherited terms kept | `platform.yaml` |
| AI budget | USD 100/month cap, USD 3/day newcomer pool (enforced from milestone 4) | `platform.yaml` |
| Screening | Disabled (`screening_enabled: false`) until milestone 4 sign-off | `platform.yaml` |
| Subscription-token fallback | Disabled | `platform.yaml` |
| Allowed external hosts | GitHub, Hugging Face, Zenodo, Software Heritage | `platform.yaml` |
| Analytics | None | `platform.yaml` |
| AI providers | Not chosen; decided after the milestone 4 shadow-mode benchmark | — |

**Computer Science overrides §14.** §14 launches only Mathematics and Economics as `active`, with Computer Science shown as a secondary discipline of legacy UnsolvedMath problems. The owner chose to launch Computer Science as a full section. Mathematical Physics stays a secondary label (`planned`, `usable_as_secondary`). Biology and Medicine stay `planned` with the §14 hold conditions.

## Still required from the owner

- **Before auto-publication:** a second organisation owner and an appeals contact (§13, §21).
- **Discipline stewards:** stewards for each active discipline. The `stewards` lists are empty for now.
- **MSC 2020 and JEL vocabularies (milestone 2):** confirm the licence terms of these vocabularies before their full lists and class names are added. Only top-level codes are included now.
