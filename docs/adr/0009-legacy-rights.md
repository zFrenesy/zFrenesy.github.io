# ADR 0009: Rights for migrated legacy material

Status: Accepted, 2026-10-11 (owner decisions during milestone 2 planning)

## Context

Spec §12 says not to apply a new blanket licence to legacy material, and to keep source-specific terms. Material whose redistribution is unclear becomes link-only. The legacy repository (`mehmetmars7/Erdosproblems-llm-hunter`) licenses only its software (Apache-2.0) and says nothing about its research content. The owner of that repository is the owner of this platform.

## Decision

The owner declared, on 2026-10-11, that the legacy research content of their repository is published under **CC BY 4.0**. The declaration is `rp/migration/legacy/owner-declarations.yaml`, copied into the research tree as `migration/legacy-b1f6331/owner-declarations.yaml`. It is an explicit, scoped owner act, not a blanket default.

| Material | Licence on the platform | Basis |
| --- | --- | --- |
| AI-generated attempts in every model folder, including reused write-ups | CC BY 4.0 | Owner declaration |
| openai/math claim summaries (`top_problems/openai/`) | CC BY 4.0 for our summaries. The linked openai/math sources remain Apache-2.0 and are not re-hosted | Owner declaration; THIRD_PARTY_NOTICES |
| Top Open Problems statements (`definitions/`) and English summaries | CC BY 4.0, **except CC BY-SA 4.0** where the UnsolvedMath source is Oberwolfach Reports (`OWR-` codes) | Owner declaration; ShareAlike cannot be relicensed |
| UnsolvedMath metadata (IDs, codes, titles, categories) | CC BY 4.0, attributed to Ulam AI and the UnsolvedMath Contributors, with a notice of changes | Upstream licence |
| Economics statements | CC BY 4.0 | Owner declaration |
| `Human_Contribution` files: summaries written by the legacy site about externally published work (Kominers; Shea; Kittle and Kogler) | CC BY 4.0 for the summary text. The underlying papers and code stay with their authors and are linked (arXiv, pinned GitHub), not re-hosted. Credited authors are `listed_by_submitter` until they confirm | Owner declaration |
| Erdős and MathOverflow statements | Link-only (never stored in the legacy repository; MathOverflow is CC BY-SA at source) | Source terms |

Every migrated record names its licence and holders in `rights` and points to the declaration in `rights.notes`. Third-party notices (UnsolvedMath, Oberwolfach, openai/math, MathOverflow) are reproduced on the site's licences page and in every revision package's `RIGHTS.md`.

## Consequences

The new site can render and package all legacy research content except the Erdős and MathOverflow statements. If a credited author objects to a summary, the takedown policy applies: the record becomes a tombstone and its package stays withheld. The declaration file is evidence in the identity mapping; it is not a substitute for the authors' own confirmation, which `/confirm-authorship` can record later (milestone 3).
