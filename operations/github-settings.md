# GitHub settings: full target configuration

For the owner, who applies all settings. This is the whole target (spec §7, §21) grouped by the milestone that needs each part. Apply only the milestones that have been signed off. Milestone 1 items are in `operations/staging-org.md`, and `operations/expected-settings.yaml` lists what the verifier checks.

## Milestone 1 (staging now; production at cutover)

**Organisation**

| Setting | Value |
| --- | --- |
| Two-factor authentication | Required |
| Base permission | Read |
| Member repository creation | Disabled |
| App installation | Owners only |

**Actions**

| Setting | Value |
| --- | --- |
| Policy | Organisation plus selected actions; GitHub-created and Marketplace-verified actions not blanket-allowed |
| Allowlist | Exact SHA-pinned refs only; currently `actions/checkout@3d3c42e…` (v7.0.1) and `actions/setup-python@5fda3b9…` (v7.0.0) |
| Require full-length SHA pinning | On |
| Default `GITHUB_TOKEN` | Read-only; Actions cannot create or approve pull requests |
| Fork PR approval | "First-time contributors who are new to GitHub" |

**Repositories**

| Setting | Value |
| --- | --- |
| Secret scanning and push protection | On for all repositories |
| `research` branches | `main` and `automation-ledger` |
| `research` environments | `intake`, `screening`, `publisher`, each limited to `main`, no secrets yet |
| Dependabot | Version updates for GitHub Actions and pip (`.github/dependabot.yml`); security updates on |

## Milestone 2

| Setting | Value |
| --- | --- |
| Pages | Source "GitHub Actions" on `<org>.github.io` |
| `pages` environment | Limited to `main`. GitHub creates one named `github-pages`; milestone 2 decides whether to use it as the spec's `pages` environment and records the choice in an ADR |

## Milestone 4 (specified in detail in the milestone 4 plan; do not apply earlier)

**GitHub Apps** (two separate registrations, §7)

| App | Rights |
| --- | --- |
| Intake App | Research-repository branch, PR and comment functions only. Not the required-check identity. No bypass of protected `main` or of the ledger. |
| Publisher App | Final required-check issuer (`rp/authorize`), controlled merge and ledger writer. Private key stored only in the `publisher` environment. |

**Rulesets on `research`** (§7)

1. `main` may be updated only through the Publisher's operational path.
2. The Publisher App check `rp/authorize` is required, and the branch must be up to date. No ordinary bypass.
3. On `automation-ledger`, only the Publisher can write. No force pushes or deletions.

**Secrets**

| Secret | Environment | Rule |
| --- | --- | --- |
| AI provider keys | `screening` | Hard spend limits set at the provider; prepaid credit where available |
| Publisher private key | `publisher` | Only here |

**Never enable** native auto-merge on `research`, and never use code-owner review combined with zero required approvals as a control.

## Milestone 5–6

| Setting | Value |
| --- | --- |
| Health check | External check for scheduled reconciliation (GitHub disables schedules after 60 days of repository inactivity) |
| Mirrors | Off-account mirrors of Git, ledger and release assets |
| Restore drill | Restore and key-rotation drill by a second maintainer |
| Production | Production organisation `we-solve` configured identically, then the separately authorised cutover |
