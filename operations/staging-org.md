# Staging organisation checklist (milestone 1)

Who does what (owner decision 2026-10-11, see CLAUDE.md):

- **Owner (done):** created the `we-solve-staging` organisation and signed in with `gh auth login`.
- **Claude Code:** applies steps 2–7 with `gh`, showing each command before running it, then runs the verifier (step 9) itself. This is deferred until milestone 2 first needs the staging org.
- **Owner only, on request:** organisation-wide settings that the API does not expose, GitHub Apps, secrets and API keys, billing and spend limits.

The steps below describe the settings in the web UI. That makes each one easy to check by hand, and some organisation settings, such as the 2FA requirement, may only be changeable there. This covers only what milestone 1 needs: Apps, secrets and rulesets come with milestone 4 (`operations/github-settings.md`).

Cost: none (GitHub Free).

## 1. Create the organisation

1. Go to <https://github.com/account/organizations/new> and choose **Free**.
2. Name it `we-solve-staging` and use your contact email. If you choose another name, change `staging.organisation` in `rp/policies/platform.yaml` and `organisation` in `operations/expected-settings.yaml`.
3. Do not add members yet. Add the second owner (§13, §21) when one is named.

## 2. Authentication and member privileges

In **Settings**:

1. **Authentication security**: tick *Require two-factor authentication for everyone in the organization*.
2. **Member privileges**:
   - *Base permissions*: **Read**.
   - *Repository creation*: untick **Public** and **Private**.
   - *Repository visibility change*, *Repository deletion and transfer*: leave **unticked**, so only owners can do these.
   - *Allow members to create teams*: untick.
3. **GitHub Apps / Third-party access**: leave the default, so only owners can install Apps and members can only request them.

## 3. Actions policy

In **Settings → Actions → General**:

1. **Policies**: choose *Allow we-solve-staging, and select non-we-solve-staging, actions and reusable workflows*.
   - Untick *Allow actions created by GitHub*.
   - Untick *Allow actions by Marketplace verified creators*.
   - Under *Allow specified actions and reusable workflows*, enter exactly:

     ```text
     actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1,
     actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97,
     actions/setup-node@820762786026740c76f36085b0efc47a31fe5020
     ```

   - Tick *Require actions to be pinned to a full-length commit SHA*.
2. **Fork pull request workflows from outside collaborators**: *Require approval for first-time contributors who are new to GitHub*.
3. **Workflow permissions**: *Read repository contents and packages permissions*. Untick *Allow GitHub Actions to create and approve pull requests*.

## 4. Secret scanning and push protection

In **Settings → Advanced Security** (named *Code security* in some accounts), apply a configuration to **all repositories** with *Secret scanning* and *Push protection* enabled. Both are free for public repositories. If you enable them per repository instead, do it in each repository after step 5.

## 5. Repositories

Create two **public** repositories, each with default branch `main` and **without** a template:

| Repository | Purpose |
| --- | --- |
| `we-solve-staging.github.io` | Staging copy of the platform and website repository |
| `research` | Staging copy of the research repository |

Then give `research` an empty `automation-ledger` branch. In an empty local folder, replacing the remote with your SSH or HTTPS URL:

```sh
git init research-staging && cd research-staging
git commit --allow-empty -m "Initialise main"
git branch -M main
git remote add origin git@github.com:we-solve-staging/research.git
git push -u origin main
git switch --orphan automation-ledger
git commit --allow-empty -m "Initialise ledger"
git push -u origin automation-ledger
```

Do **not** push the platform code yet. Milestone 2 publishes it to `we-solve-staging.github.io` with Pages enabled.

## 6. Environments in `research`

In **research → Settings → Environments**, create `intake`, `screening` and `publisher`. For each one:

- Set *Deployment branches and tags* to **Selected branches and tags**, then add the branch rule `main`.
- Add no secrets, variables or required reviewers yet; milestone 4 specifies them.

The `pages` environment (§21) belongs to the platform repository and is set up with Pages in milestone 2.

## 7. Pages

In **we-solve-staging.github.io → Settings → Pages**, set *Source* to **GitHub Actions**. Nothing deploys until milestone 2.

## 8. Token for verification

The verifier uses the owner's `gh` login (`gh auth token`). Reading some organisation settings, such as the 2FA requirement, may need the `admin:org` scope. If a check fails as "not present in the API response", Claude Code asks the owner to run `gh auth refresh -s admin:org` and does not change scopes itself.

## 9. Verify

```sh
cd "/path/to/we-solve"
GITHUB_TOKEN="$(gh auth token)" ~/.venvs/we-solve/bin/python -m rp.ops.verify_settings --org we-solve-staging
```

Every line must say `PASS`. The tool sends only GET requests. A `FAIL` saying a field is "not present in the API response" usually means the token cannot see that setting. It never counts as a pass.

Field names follow the GitHub REST API (2022-11-28). If GitHub has renamed one, the check fails closed. Note it in the milestone sign-off and the field mapping will be updated in `rp/ops/verify_settings.py`.

## 10. Record

Note the date and the verifier output in the milestone 1 sign-off. Re-run step 9 at every milestone sign-off to catch drift.
