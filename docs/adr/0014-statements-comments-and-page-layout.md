# ADR 0014: Statements, comments and page layout

Status: Accepted, 2026-10-11, following the owner's review after milestone 3.

## Statements and catalogue links

Erdős pages display a statement, following the legacy site's practice of
extracting a labelled restatement from a manuscript. This supersedes the
link-only Erdős statement presentation in ADRs 0009–0011. It does not change
the MathOverflow policy or assert a licence for erdosproblems.com text.

`rp.migration.erdos_statements` extracts exact, bounded source slices from
already accepted manuscripts with permitted redistribution. It prefers a
formal restatement, keeps qualifications in that section, and records the
contribution, immutable revision, original source commit, digest and character
range. Seven nonstandard headings have explicit reviewed selections; arbitrary
opening prose and proof sections are never used as fallback statements.

Each of the 1,221 Erdős problems receives a new statement revision with the
manuscript's rights and attribution, plus an appended `statement_revised`
ledger event and descriptor. Previous descriptors and events, contribution
bytes, contribution targets and aliases remain unchanged. The old stub remains
available in Git history. A manifest records every source selection. Reruns
leave existing migrated revisions unchanged; a missing excerpt stops an apply
before writing any records. The ordinary site build validates the resulting
research/ledger pair before publication.

Every Erdős page links to its original erdosproblems.com page and displays
“Tao’s database” separately from the recorded source status. UnsolvedMath pages
retain their migrated statements, licences and attribution, and use their
recorded problem-code URL for a clearly labelled UnsolvedMath catalogue link.

## Comments

The owner requested giscus on problem and attempt pages. This is an explicit
exception to the earlier no-third-party-embeds policy. Comments use GitHub
Discussions in the configured research repository's Announcements category.
The owner installs the existing giscus App separately; enabling Discussions
and preparing widgets do not install or create an App or secret.

`site/comments.json` selects configuration by research repository. No staging
configuration is silently reused for production. A reader chooses **Load
comments** before any giscus request. The privacy page explains the connection,
public comments and GitHub sign-in. A GitHub discussion link remains available
without JavaScript or if loading fails. No discussion or test comment is posted
by the build or migration.

Strict, explicit discussion keys are `we-solve:<problem alias>` and
`we-solve:<contribution alias>:<revision label>`. Problem pagination shares its
thread. An attempt's latest route shares the current immutable revision's
thread; later revisions get separate threads. Theme updates use giscus's
message interface; incoming messages must match both its origin and iframe.

## Presentation and compatibility

Problem and contribution pages use a wide mathematics column and a narrower
right sidebar for contribution routes, sources and record details. Small
screens stack the sidebar below the main content. Comments follow the main
content. Mathematics rendering and document-scoped references are unchanged.

First-party site labels, policies, citations, contribution guides and generated
forms say **LLM**. Existing record enum keys and submitted issue forms remain
compatible. Archived manuscript text and names such as OpenAI are preserved.
The research kit must be regenerated at the platform commit containing these
changes so that its forms match the deployed site and parser.

## Deployment and activation

Use disposable research and ledger checkouts at the accepted staging pins:

```sh
python -m rp.migration.erdos_statements --work WORK \
  --source-commit ORIGINAL_RESEARCH_SHA --apply
```

Run the full tests, build with Pagefind and publication checks, inspect desktop
and mobile pages, then publish the platform, regenerated research kit and
migration, and appended ledger through the staging procedure in
`operations/milestone-2.md`. Record the exact three commits and Pages run.

Comments become usable after the owner installs
<https://github.com/apps/giscus/installations/new> for only
`we-solve-staging/research`. The owner deferred that installation; widget
preparation and deployment must not be reported as successful comment posting.
After installation, check a problem and immutable attempt revision without
posting an unsolicited test comment. Milestone 3's separate intake App and
milestone 4 automation remain outside this change.

## Staging checkpoint

The implementation and migration were published at these immutable revisions:

| Input | Commit |
| --- | --- |
| Platform | `a4cee165b0d0b339c95c571161711e5db7593e75` |
| Research and regenerated kit | `b67a7776559f753f4aa399e91d2d0887ae359916` |
| Ledger | `32fbf11c3ab7e4011b8b9a6ef4173758abe0d146` |

Local validation: 754 tests passed, one optional full legacy-import test
skipped; all 28 staging settings checks passed. All 1,221 source slices,
digests, rights fields and statement mappings were checked. The full build
contains 6,155 problems, 5,154 contribution revisions and 29,666 HTML pages,
with no rendering or publication-check errors. Unsupported constructs remain
in source boxes (362 boxes across 252 of 11,184 rendered documents).

Desktop (1280 px) and mobile (375 px) browser checks covered Erdős #1,
UnsolvedMath TOP-6, immutable and latest attempt routes, all seven reviewed
statement-heading exceptions, long equations, dark mode, opt-in comments and
comment-load retry. No page overflow or browser errors were found in these
checks. Giscus configuration was checked with a simulated client; App
installation and real comment posting remain deferred by the owner.

GitHub platform tests passed in
[run 38176574477](https://github.com/we-solve-staging/we-solve-staging.github.io/actions/runs/38176574477).
Pages publication succeeded in
[run 38176750641](https://github.com/we-solve-staging/we-solve-staging.github.io/actions/runs/38176750641).
Its evidence confirms all three input commits above, Python 3.12.14 and Node
22.23.3. The validated site is 574,961,833 bytes; the largest initial payload
under the existing manuscript-exclusion budget is 160,940 bytes.

Live checks passed after deployment: Erdős #1, TOP-6 and an attempt revision at
desktop and mobile widths; latest/revision discussion-key agreement; no initial
third-party requests; source catalogue links; homepage, search and citation
routes; and equality of the deployed site/CSS/MathJax/search assets with the
repository. Giscus activation remains pending the deferred owner installation.
