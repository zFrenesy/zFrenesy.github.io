# ADR 0011: Site routes and TeX rendering

Status: Accepted, 2026-10-11; implemented and locally exercised in milestone 2. Full-corpus and staging publication acceptance are tracked separately in `docs/acceptance-matrix.md`.

## Context

Spec §19 asks for build-time rendering with Pandoc, MathJax on maths pages only, source fallbacks, and the listed routes. The legacy site already has a TeX-to-HTML formatter, `formatTeX` in `docs/problem.html`, with about 150 regression assertions. It is tuned to exactly this corpus. The owner's rendering guidance is to preserve that tested behaviour first, keep MathJax 3 as the only maths engine, process documents at build time, load and typeset less, and benchmark alternatives later.

## Decision

**Engine (departure from §19's "Pandoc").**

- `formatTeX`, `tex-bare-math.js` and `tex-references.js` are lifted unchanged from the pinned legacy commit into `site/renderer/`, with provenance in `site/renderer/PROVENANCE.json`. The MathJax configuration moves to `mathjax-config.js`.
- The trusted formatter runs at build time through `rp.render.tex`, with a Node `vm` context, disabled string/Wasm code generation and per-document execution timeouts. Manuscript text is supplied as data, never evaluated as JavaScript. The context does not expose `require` or `process`; **Node `vm` is not a security boundary**. The separate CI build step uses a network namespace without external networking, runs under the ordinary runner UID/GID, and has job/subprocess timeouts. Local CLI use does not acquire that operating-system boundary automatically.
- Batches and cached results limit repeated work. Cache keys include prepared input, renderer bundle, post-processing version and Node major version. Contributor scripts, TeX build commands and external artifacts are not executed.
- Pandoc and LaTeXML are optional backends to benchmark later, not part of the pinned toolchain.

**Build-time additions around the extracted renderer.**

- **Source boxes.** Converted paragraph, list-item, heading or table-cell content that still contains TeX commands outside recognised mathematics/literal code is replaced by an escaped source box. It carries the `tex-source-box` and `mathjax-ignore` classes, so MathJax never typesets it, and is counted in the rendering report. Generated label anchors are retained outside the box. A per-document formatter failure produces a source fallback; failure of the runner itself fails the build. Original manuscript downloads retain their exact bytes; a boxed converted passage is not represented as an exact source-range reconstruction.
- **Scope fragments.** A separately displayed scope and its manuscript body independently retain rendered content or source fallback. Mathematical loading, labels, source-box counts and leftover-command diagnostics account for both; scope conversion errors have an explicit report counter.
- **Sanitising.** `nh3` applies an allowlist of tags, attributes and URL schemes. Links get `rel="noopener noreferrer nofollow ugc"` and `referrerpolicy="no-referrer"`.
- **Macro scope.** Each document is rendered on its own. Its macros are not visible to any other document.
- **Labels.** `rp.site.references` processes the sanitised HTML and writes a reference index keyed by `[writeup alias, immutable revision, imported source scope, TeX label]`. Stable anchor IDs depend on those values, never on page order. Duplicate labels remain ambiguous and receive diagnostics.

**Reference resolution.**

- The builder first indexes supplied documents, including their displayed scope fragments, then resolves contribution references. A local label takes precedence. Missing local labels may use a declared `derivative_of`, `extends` or `reuses` target only when the relationship is known and names the exact immutable revision supplied in this build. `possible_revision_of` is insufficient.
- One matching external target creates a link to that revision and names its alias/revision in the displayed reference. Several matching targets remain visibly unresolved; no earlier page or neighbouring version is guessed. An ambiguous local label never falls through to an external target.
- References preserve imported source scopes so labels in a reused collection cannot accidentally bind to a different source section. The manifest is published at `/api/v1/references.json`; unresolved/ambiguous cases are reported in the build data.
- The resolver uses existing section/theorem captions where available. **Equation references retain their label text; it does not fabricate equation numbers or alignment-row ownership.** The extracted formatter has already lost information needed to assign every multiline label to its original row reliably.
- A ledger entry for a historical revision is not enough to reconstruct its manuscript. When that revision's source snapshot is absent from the supplied research tree, its route contains an explicit placeholder; current sources and citations are not substituted. Revision packages are generated only for supplied records permitting redistribution. Records marked `link_only` or `unclear` remain metadata/source links; their source bodies are not rendered, downloadable or packaged.

**Browser.**

- MathJax 3.2.2 is self-hosted from the pinned npm tarball; `VENDOR.json` lists the digest of every file.
- It is loaded only on pages that contain maths, and typesets only the manuscript or statement container.
- Its configuration keeps the legacy macros, `ui/safe` with URLs disabled, and assistive MathML. The frontend wrapper disables the legacy error-suppressing extensions, records compile/typeset failures and replaces failed expressions with escaped source boxes. A loader failure leaves the available notation and a visible notice.
- Allowed dynamic TeX extensions are restricted to the vendored set. MathJax's context menu is disabled because enabling its SRE speech features can request unvendored CDN locale data. Assistive MathML remains enabled; that feature alone is not an accessibility audit.
- Problem pages show summaries. Each manuscript lives on its own revision page, so equation numbers cannot depend on what else was opened.

**Routes.**

| Route | Page |
| --- | --- |
| `/problems/<alias>/` | Problem |
| `/contributions/<alias>/` | Contribution (latest revision) |
| `/contributions/<alias>/<rK>/` | Immutable revision; citations point here |
| `/p/<uuid-hex>/`, `/c/<uuid-hex>/` | Redirect stubs to the alias pages |

Discipline sections live at `/mathematics/`, `/economics/` and `/computer-science/`, as do the other §19 routes. A configured base URL supports project Pages prefixes. The legacy URL map and redirect text are generated as build data; nothing writes to the legacy repository. Applying legacy redirects remains milestone 6 cutover work.

**Budgets enforced by the build.**

- At most 200 KiB of first-party payload per page, excluding MathJax and manuscript or statement fragments.
- Under 800 MiB in total.
- No third-party requests. The legacy site's Google Analytics tag is not carried over.
- No broken internal links.

`rp.site.checks` reads each HTML/SVG document once, checks local paths and anchors, rejects duplicate IDs and remote HTML/CSS subresources, and accounts for each initial local resource once through its CSS dependencies. `data-payload-exclude` marks manuscript/statement content for payload accounting; those contents still undergo link/resource checks. MathJax is excluded from the per-page payload budget but must be self-hosted and present, including the engine declared through `data-mathjax-src`. ZIP/PDF packages are rejected from Pages output and are generated separately for later immutable Release publication. Runtime JavaScript networking is covered by browser checks, not inferred from arbitrary bundle strings.

**Measured local evidence.**

The seed-1 §11 fixture produced 105 problems, 500 attempts, 60 reviews, 201 people and 54 revised contributions. A local build with an empty rendering cache, Pagefind and 510 separate packages took 18.04 seconds after 6.41 seconds of fixture generation. Fifty legacy records with unclear redistribution rights remained metadata without source downloads or ZIPs. Its 2,487 HTML pages occupied 23,745,163 total Pages bytes; the largest initial payload was the search page at 173,884 bytes. All static publication checks passed, including the strengthened input-integrity checks. Toolchain and limits of this single synthetic measurement are recorded in [the acceptance matrix](../acceptance-matrix.md).

First-party pages, assets, source downloads, citations and revision packages repeat byte-for-byte for the tested fixed inputs. Pagefind 1.5.2 filter ordering can change search-index hashes and small byte totals between otherwise identical builds. Search output is checked each run; whole-tree byte identity is not claimed.

## Consequences

The extracted formatter preserves the legacy compatibility baseline, while sanitisation, reference resolution and explicit fallbacks intentionally change some output. The ported regression tests and site integration tests guard that contract; they do not establish perfect visual or semantic handling of arbitrary TeX. General preamble macro programming, complete package support, reliable equation-row numbering and exact source-range diagnostics remain outside this implementation.

Moving to Pandoc, LaTeXML, MathJax 4 or pre-rendered maths later requires a measured comparison against the same corpus. The module is separated from site generation under `rp/render` and `site/renderer`; publishing it as an independent collaboration repository is later work. No staging deployment or full-corpus success follows merely from this decision or the synthetic benchmark.
