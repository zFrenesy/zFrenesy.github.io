# we-solve

A static research archive with explicit attribution, immutable revision identities,
source downloads, scoped search and visible rendering fallbacks. A contribution's
claim is separate from its source catalogue's status and from review evidence.

The current work is milestone 2. Submission automation, screening and release-asset
publication belong to later milestones. See [the specification](docs/IMPLEMENTATION_SPEC.md),
[accepted decisions](docs/adr/) and [acceptance evidence](docs/acceptance-matrix.md).

## Develop

Use Python 3.12.14 and Node 22.23.3, matching the staging workflow. Keep the virtual
environment outside this checkout, then install the locked dependencies:

```sh
python -m pip install --require-hashes --no-deps -r requirements/dev.txt
python -m pytest
```

The optional full migration test uses `RP_LEGACY_CLONE` to identify a read-only
clone. Ordinary tests create their own synthetic repository and ledger.

## Build

The input checkpoint contains `research/` and `ledger/events.jsonl`. Use a fresh
output directory and keep revision packages outside the Pages directory:

```sh
python -m rp.site build \
  --work /path/to/checkpoint \
  --out /tmp/we-solve-site \
  --cache-dir /tmp/we-solve-tex-cache \
  --packages-dir /tmp/we-solve-packages \
  --base-url https://we-solve-staging.github.io/ \
  --report /tmp/we-solve-report.json
```

The build checks accepted source fingerprints, statements and ledger identities;
renders and sanitises documents; creates pages, citation metadata and Pagefind
search; then checks local links, assets and payload budgets. Research source is
treated as data. The build never executes contributor programs or a TeX engine.

Serve a local result with `python -m http.server --directory /tmp/we-solve-site`.
If the configured base URL has a path prefix, serve the output under that same
prefix. MathJax and search assets are self-hosted.

## Rendering modules

- `rp/render/tex.py`: preparation, cached build-time rendering, sanitisation and
  source fallbacks.
- `site/renderer/`: the preserved legacy formatter, provenance and Node adapter.
- `rp/site/references.py`: document/revision/scoped labels and conservative
  cross-document reference resolution.
- `site/assets/mathjax-init.js`: browser typesetting, accessibility and expression
  error fallbacks around the preserved MathJax configuration.

The renderer is deliberately modular, but this checkout remains its supported
build environment. Backend replacement or extraction into a separate project
should retain the corpus fixtures and regression tests. Unsupported TeX is shown
as source; the archive does not claim complete TeX compatibility.

First-party pages and revision packages are deterministic. Pagefind 1.5.2 may
reorder generated index entries, so its generated hashes can differ between runs.

## Staging

[Staging operations](operations/milestone-2.md) describes pinned input commits,
GitHub settings and the manually dispatched Pages workflow. Publication uses a
separate job after tests and validation succeed. ZIP packages remain local during
this milestone; public release downloads are pending the publication milestone.

The legacy repository and production organisation are outside this staging
workflow. Software uses Apache-2.0; research and third-party rights are recorded
per document and preserved in revision packages.
