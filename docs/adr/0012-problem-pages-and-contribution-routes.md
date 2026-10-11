# ADR 0012: Simpler problem pages and contribution routes

Status: Accepted, 2026-10-11 (owner review of the milestone 2 staging site).

## Context

The owner reviewed the staging site and asked for:

- a simpler design with a visible dark/light switch;
- one status line instead of the status box;
- the latest contributions readable on the problem page;
- contribution routes that actually work, including coding agents that open pull requests themselves.

No contributor intake existed yet: `/contribute/attempt/?problem=…` showed nothing.

## Decision

**Status line (departure from §19's three-part status panel).** Problem pages and listing rows show a single line:

- **Source status:** Open, Partially solved or Solved. `solved`, `proved`, `disproved` and `independent` all read as Solved. It is omitted when the source records no status; no status is invented.
- **LLM status:** Solved if any contribution claims a full solution or disproof, Partially solved if any claims a partial or conditional result, otherwise Open. It is always labelled unverified.

Reviews, screening and formal checking remain separate records and appear with each contribution, not in the line. Claims never change the source status.

**Inline manuscripts (departure from ADR 0011, "problem pages show summaries").**

- The latest three attempts appear on the problem page with their rendered manuscripts. Each is collapsed after about 380 px with "View more", and links to its own revision page.
- Older attempts and reviews are listed as links.
- The statement collapses after about three paragraphs.
- MathJax typesets each manuscript separately and calls `texReset()` before each one, so equation numbers and labels cannot leak between documents.
- Manuscripts stay outside the page payload budget (`data-payload-exclude`), as before.

**Contribution routes (part of milestone 3 brought forward).** Every problem page has a Contribute panel with four routes (§20):

1. A prefilled issue form.
2. A research prompt for chat assistants, generated at build time under `/prompts/`.
3. Codespaces, `codex://` and `claude-cli://` links plus copyable terminal commands.
4. Fork and pull request steps.

The site's link checker accepts `codex:` and `claude-cli:` only for anchors; page subresources stay local.

**Contributor tools.** The `rp` command gains `start`, `new`, `check` and `submit`:

- `rp check` is the same code as the pull-request check.
- `rp submit` uses the contributor's own `git` identity and `gh` login.
- Legal declarations are confirmed only by a person at an interactive terminal or through the issue-form checkboxes, never by an agent's `--yes`.

**Research repository kit.** Rendered from `rp/contribute/kit/` at a pinned platform commit. It contains:

- `AGENTS.md` (legacy prompts A–D adapted), `CLAUDE.md` and `.gemini/settings.json`;
- `CONTRIBUTING.md`, the issue forms and the PR template;
- a dev container pinned by digest;
- a thin `check.yml` that calls the SHA-pinned reusable workflow `.github/workflows/research-check.yml`. That workflow checks out the merge result with credentials disabled, runs only platform code, and executes nothing from the contribution.

**Queueing.** Pull requests and issues are checked but never merged by hand. They wait for the milestone 3–5 intake, screening and publication automation.

## Consequences

- The pull-request check is advisory until the milestone 4 gate. A pull request can edit its own `check.yml`, and fork runs may need approval, so no required path depends on it (§8.1).
- The dev container installs `rp` and `gh` only. TeX Live and Pandoc are left out because of their size (the site does not use Pandoc; ADR 0011). Contributors who want to compile TeX add the TeX feature locally.
- `claude-cli://` links need a local clone that Claude Code has opened before. The panel says so and also offers the plain commands.
- Changing the platform commit used by the research repository means re-rendering the kit (`python -m rp.contribute.kit`) and pushing it to the research repository (`operations/research-kit.md`).
