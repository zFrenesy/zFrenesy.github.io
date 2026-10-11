# ADR 0001: Stack, dependency pins and Python version

Status: Accepted, 2026-10-11 (milestone 1 plan)

## Context

The spec (§2, CLAUDE.md) fixes Python 3.12, JSON Schema 2020-12, Jinja2, Pandoc, MathJax and Pagefind, and requires every dependency, action and image to be pinned. The development machine has Python 3.13 and 3.14 but not 3.12. The working copy lives in Google Drive, which syncs every file it contains.

## Decision

- The code targets Python 3.12 (`requires-python >=3.12`) and avoids 3.13-only features. CI runs on 3.12. Local development uses a 3.13 virtualenv at `~/.venvs/we-solve`, outside Google Drive. Pytest runs with `-p no:cacheprovider`, so no cache directories land in Drive.
- Dependencies are exact-pinned in `requirements/dev.txt`, with the SHA-256 of every file PyPI publishes for each version (`pip install --require-hashes --no-deps`). This lets one lock serve macOS and Linux and Python 3.12 and 3.13. Conditional dependencies such as `typing-extensions` for Python < 3.13 carry their markers.
- New pins should be releases at least two weeks old. For example, iniconfig 2.3.0 and rpds-py 2026.6.3 were chosen over versions published days before this ADR.
- To regenerate the lock, read each version's file digests from `https://pypi.org/pypi/<name>/<version>/json`, which is what pip-tools does. Dependabot (§21) will propose updates once the repository is on GitHub.
- Actions are pinned to full commit SHAs resolved with `git ls-remote`:
  - `actions/checkout` v7.0.1 is `3d3c42e5aac5ba805825da76410c181273ba90b1`.
  - `actions/setup-python` v7.0.0 is `5fda3b95a4ea91299a34e894583c3862153e4b97`.

  The CI workflow has `permissions: contents: read` and `persist-credentials: false`.
- Milestone 1 needs only PyYAML, jsonschema (with referencing and rpds-py) and pytest. Jinja2, Pandoc and Pagefind are pinned when milestone 2 first uses them.
- The package is `rp`. Schemas, policies and profiles are package data under `rp/schemas`, `rp/policies` and `rp/profiles`, matching the layout in spec §2. Spec references such as `policies/prices.yaml` resolve inside `rp/`.

## Consequences

The local and CI interpreters differ by one minor version. CI on 3.12 is the reference, so any 3.13-only construct fails there. To match exactly, the owner can install `python@3.12` and recreate the virtualenv.
