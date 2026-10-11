# ADR 0015: Catalogue discovery and status display

Status: Accepted, 2026-10-11, following the owner's staging-site review.

## Problem pages and status

The problem sidebar omits internal statement-revision IDs and verbose rights
holder/notes text. The records retain all provenance and rights metadata;
statement attribution, licence and original-source links remain visible.
Contribution-route links sit below their copy buttons, and inline attempts
link to “Go to contribution”.

When the authoritative source status normalizes to **Solved**, the displayed
LLM status also reads **Solved**, labelled “from source status”. This is a
presentation rule; it does not claim that an LLM found a solution. Otherwise
LLM status continues to reflect unverified contribution claims. The reverse
rule never applies: LLM claims do not update an authoritative source status.
This refines the claim-only LLM display in ADR 0012.

## Economics discovery and ranking

Economics listings follow the exact current-rank order from the pinned legacy
catalogue, independently of immutable aliases and initial ranks. The editable
CSV and JEL vocabulary live in `site/catalogues/`, owned by the trusted platform.
See [the operations guide](../../operations/economics-catalogue.md) for changing
the order and validating the configuration. No research or ledger migration is
needed when changing presentation order. New, unranked entries sort after
ranked entries without an invented numeric rank.

Economics home, catalogue and source pages offer search by JEL code, subject
name, problem identifier and title. Search covers every record in that view,
not only its current static page, and preserves ranking. It loads a compact
local metadata index only when used, renders 30 results per page, and supports
shareable `?q=` URLs. Parent JEL codes and names match their descendant codes.
Static JEL browse pages remain usable without JavaScript; a failed search
request leaves the ordinary catalogue available. JEL terms also participate
in the site's Pagefind search and filters.

## Cross-listing

`site/catalogues/cross-listings.json` includes Top Open Problems in Mathematics,
including records whose primary discipline is Computer Science. They also
remain in Computer Science, with the same canonical problem page, attempts and
identifier. The rule applies to section counts, lists, metadata facets and
search filters; it does not duplicate records or mutate canonical discipline
metadata. Other catalogue orderings retain their existing numeric order.

## Validation

Tests cover one-way status inheritance, legacy ranking parity and malformed
configuration, full scoped economics indexes, JEL routes and labels, source
metadata preservation, and cross-listing without duplicate canonical records.
Browser checks cover code/name queries, parent categories, result pagination,
query links, clear/retry behavior, deployment base paths and mobile layout.
The existing full static build verifies routes and publication budgets before
the GitHub Pages deployment.
