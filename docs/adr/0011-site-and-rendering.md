# ADR 0011: Site routes and TeX rendering

Status: Accepted, 2026-10-11 (milestone 2 plan; owner decision on the rendering engine)

## Context

Spec §19 asks for build-time rendering with Pandoc, MathJax on maths pages only, source fallbacks, and the listed routes. The legacy site already has a TeX-to-HTML formatter, `formatTeX` in `docs/problem.html`, with about 150 regression assertions. It is tuned to exactly this corpus. The owner's rendering guidance is to preserve that tested behaviour first, keep MathJax 3 as the only maths engine, process documents at build time, load and typeset less, and benchmark alternatives later.

## Decision

**Engine (departure from §19's "Pandoc").**

- `formatTeX`, `tex-bare-math.js` and `tex-references.js` are lifted unchanged from the pinned legacy commit into `site/renderer/`, with provenance in `site/renderer/PROVENANCE.json`. The MathJax configuration moves to `mathjax-config.js`.
- The renderer runs at build time under Node, inside a `vm` context with no module, file or network access, through `rp.render.tex`.
- Pandoc and LaTeXML are optional backends to benchmark later, not part of the pinned toolchain.

**Build-time additions around the extracted renderer.**

- **Source boxes.** A paragraph that still contains TeX commands outside maths after conversion is replaced by an escaped source box. It carries the `tex-source-box` and `mathjax-ignore` classes, so MathJax never typesets it, and is counted in the rendering report.
- **Sanitising.** `nh3` applies an allowlist of tags, attributes and URL schemes. Links get `rel="noopener noreferrer nofollow ugc"` and `referrerpolicy="no-referrer"`.
- **Macro scope.** Each document is rendered on its own. Its macros are not visible to any other document.
- **Labels.** `\label` keys found at build time are written to a reference index keyed by writeup alias, immutable revision label and TeX label.

**Browser.**

- MathJax 3.2.2 is self-hosted from the pinned npm tarball; `VENDOR.json` lists the digest of every file.
- It is loaded only on pages that contain maths, and typesets only the manuscript or statement container.
- Its configuration keeps the legacy macros, `ui/safe` with URLs disabled, and assistive MathML. `formatError` replaces an expression that fails to typeset with its source.
- Problem pages show summaries. Each manuscript lives on its own revision page, so equation numbers cannot depend on what else was opened.

**Routes.**

| Route | Page |
| --- | --- |
| `/problems/<alias>/` | Problem |
| `/contributions/<alias>/` | Contribution (latest revision) |
| `/contributions/<alias>/<rK>/` | Immutable revision; citations point here |
| `/p/<uuid-hex>/`, `/c/<uuid-hex>/` | Redirect stubs to the alias pages |

Discipline sections live at `/mathematics/`, `/economics/` and `/computer-science/`, as do the other §19 routes. The legacy URL map is generated as data plus stubs for the legacy repository and applied only at the milestone 6 cutover.

**Budgets enforced by the build.**

- At most 200 KiB of first-party payload per page, excluding MathJax and manuscript or statement fragments.
- Under 800 MiB in total.
- No third-party requests. The legacy site's Google Analytics tag is not carried over.
- No broken internal links.

## Consequences

Rendering output matches what readers of the legacy site saw, and the ported legacy tests guard it. Moving to Pandoc, LaTeXML, MathJax 4 or pre-rendered maths later is a measured change against the same corpus. The extracted module can serve the legacy site after cutover.
