# Milestone 2 staging build and publication

The trusted workflow is [pages.yml](../.github/workflows/pages.yml). Pushes run
the ordinary code tests. A manual dispatch on the staging platform's `main`
builds, validates and deploys the full archive. There is no pull-request deploy.
The build checks out an exact platform revision and two explicitly selected
research-repository commits: accepted source from `main`, and `events.jsonl`
from `automation-ledger`. The selected commits must belong to those branches.

This is staging publication only. It does not activate the milestone 5
controller or publish revision packages to Releases. The owner has already
authorized staging repository/settings operations through `gh`, with exact
commands shown before execution (CLAUDE.md). GitHub Apps, secrets, API keys,
billing and production changes retain their separate approval requirements.

## Reproducible inputs and outputs

The directory supplied to the builder has this shape:

```text
work/
  research/                 # research repository, accepted main commit
    problems/...
    migration/...
  ledger/                   # research repository, automation-ledger commit
    events.jsonl
```

The workflow accepts `research_sha` and `ledger_sha` inputs. When an input is
empty, it uses the nonsecret repository variable `STAGING_RESEARCH_SHA` or
`STAGING_LEDGER_SHA`. Every pin must be a full, lowercase 40-character commit
SHA. Moving a branch never silently changes a configured build input. Update
the variables only after checking that the pair describes the intended
accepted archive and ledger checkpoint.

The build uses Python 3.12.14, Node 22.23.3, the hash-locked requirements, and
the vendored MathJax files. Tests run against trusted platform code. Rendering,
search indexing and site validation then run in a network namespace with the
runner's ordinary UID/GID. Contributor files are read as data; their scripts,
dependency files and workflows are not run. The build job has read-only
repository access and no deploy token. A separate job deploys only a successful
artifact from the same run, through the `pages` environment.

Rendered-document caches are keyed by platform renderer/dependency inputs and
the research commit; each entry also retains the renderer's own source/config
key. Packages live under the runner's temporary directory, outside `_site`.
Only `_site` is uploaded as the Pages artifact. `site-build-evidence` retains
the report and exact input SHAs for seven days. It contains no revision ZIPs.

The pinned runner label `ubuntu-24.04` is a maintained GitHub-hosted image,
not an immutable image digest. Input SHAs, language versions, dependencies and
actions are pinned; the evidence is sufficient to reproduce the selected data
and rendering configuration, but does not assert bit-for-bit OS identity.

## Action pins

These refs were checked against the official action repositories on
2026-10-11. All selected releases were at least two weeks old. Python 3.12.15
was only ten days old, so the workflow selects 3.12.14 instead.

| Action | Release | Full commit |
| --- | --- | --- |
| `actions/checkout` | v7.0.1 | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| `actions/setup-python` | v7.0.0 | `5fda3b95a4ea91299a34e894583c3862153e4b97` |
| `actions/setup-node` | v7.0.0 | `820762786026740c76f36085b0efc47a31fe5020` |
| `actions/cache` | v6.1.0 | `55cc8345863c7cc4c66a329aec7e433d2d1c52a9` |
| `actions/upload-artifact` | v7.0.0 | `bbbca2ddaa5d8feaa63e36b76fdaad77386f024f` |
| `actions/upload-pages-artifact` | v5.0.0 | `fc324d3547104276b827a68afc52ff2a11cc49c9` |
| `actions/deploy-pages` | v5.0.1 | `368f82528645a54fb793d4d04e342629a3f51346` |

`upload-pages-artifact` itself invokes the listed `upload-artifact` commit, so
the latter belongs in the organisation allowlist even without the evidence
upload step. The [`upload-pages-artifact` implementation](https://github.com/actions/upload-pages-artifact/blob/fc324d3547104276b827a68afc52ff2a11cc49c9/action.yml)
records that nested dependency. [GitHub's custom Pages workflow guide](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
describes the separate build/deploy jobs and required deploy permissions.

## Apply staging settings

Show each command to the owner before executing it. Read the current API state
first, and skip already satisfied settings. The creation commands below are
for missing resources: repeated POSTs can create duplicate branch policies.
Do not print `gh auth token` or commit it to a file.

The desired organisation settings are 2FA required and base permission read.
Disable member repository creation if it is not already disabled:

```sh
gh api --method PATCH orgs/we-solve-staging \
  -f default_repository_permission=read \
  -F members_can_create_repositories=false \
  -F members_can_create_public_repositories=false \
  -F members_can_create_private_repositories=false

gh api --method PUT orgs/we-solve-staging/actions/permissions \
  -f enabled_repositories=all -f allowed_actions=selected \
  -F sha_pinning_required=true

gh api --method PUT orgs/we-solve-staging/actions/permissions/selected-actions --input - <<'JSON'
{
  "github_owned_allowed": false,
  "verified_allowed": false,
  "patterns_allowed": [
    "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
    "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
    "actions/setup-node@820762786026740c76f36085b0efc47a31fe5020",
    "actions/cache@55cc8345863c7cc4c66a329aec7e433d2d1c52a9",
    "actions/upload-artifact@bbbca2ddaa5d8feaa63e36b76fdaad77386f024f",
    "actions/upload-pages-artifact@fc324d3547104276b827a68afc52ff2a11cc49c9",
    "actions/deploy-pages@368f82528645a54fb793d4d04e342629a3f51346"
  ]
}
JSON

gh api --method PUT orgs/we-solve-staging/actions/permissions/workflow \
  -f default_workflow_permissions=read -F can_approve_pull_request_reviews=false

gh api --method PUT orgs/we-solve-staging/actions/permissions/fork-pr-contributor-approval \
  -f approval_policy=first_time_contributors_new_to_github

gh repo create we-solve-staging/we-solve-staging.github.io --public
gh repo create we-solve-staging/research --public
```

Apply security scanning and Dependabot security updates to each public repo:

```sh
for staging_repo in we-solve-staging.github.io research; do
  gh api --method PATCH "repos/we-solve-staging/$staging_repo" --input - <<'JSON'
{
  "security_and_analysis": {
    "secret_scanning": {"status": "enabled"},
    "secret_scanning_push_protection": {"status": "enabled"}
  }
}
JSON
  gh api --method PUT "repos/we-solve-staging/$staging_repo/vulnerability-alerts"
  gh api --method PUT "repos/we-solve-staging/$staging_repo/automated-security-fixes"
done
```

Publish the approved research tree to `research:main` and the exported ledger
to `research:automation-ledger`, preserving their contents. These are two
different Git roots. Verify their local records and ledger first, then use
explicit staging remotes and explicit branch destinations. Do not reuse a
remote that points to the production or legacy repository. Public commit
messages should remain general, such as `Update research` and `Update ledger`.
Record both resulting full commit SHAs before proceeding.

The following commands use shell variables set to those reviewed commits:

```sh
gh api --method PATCH repos/we-solve-staging/research -f default_branch=main

gh variable set STAGING_RESEARCH_SHA --repo we-solve-staging/we-solve-staging.github.io --body "$staging_research_sha"
gh variable set STAGING_LEDGER_SHA --repo we-solve-staging/we-solve-staging.github.io --body "$staging_ledger_sha"
```

Create research environments and their branch restrictions:

```sh
for staging_env in intake screening publisher; do
  gh api --method PUT "repos/we-solve-staging/research/environments/$staging_env" --input - <<'JSON'
{"deployment_branch_policy":{"protected_branches":false,"custom_branch_policies":true}}
JSON
  gh api --method POST "repos/we-solve-staging/research/environments/$staging_env/deployment-branch-policies" \
    -f name=main -f type=branch
done

gh api --method PUT repos/we-solve-staging/we-solve-staging.github.io/environments/pages --input - <<'JSON'
{"deployment_branch_policy":{"protected_branches":false,"custom_branch_policies":true}}
JSON

gh api --method POST repos/we-solve-staging/we-solve-staging.github.io/environments/pages/deployment-branch-policies \
  -f name=main -f type=branch
```

Publish the reviewed platform `main` to the staging platform repo. Only source
and trusted workflow files belong on this branch; generated HTML, caches and
ZIPs stay outside it. Its push runs the ordinary tests in `ci.yml`; it does not
build or upload a Pages artifact. A manual `pages.yml` dispatch performs the
full Pages build and deployment. Once `main` exists, configure Pages if needed:

```sh
gh api --method PATCH repos/we-solve-staging/we-solve-staging.github.io -f default_branch=main
gh api --method POST repos/we-solve-staging/we-solve-staging.github.io/pages -f build_type=workflow
```

If Pages already exists, update it with `--method PUT` after checking the GET
response; do not treat an unexpected creation failure as success. The workflow
uses the environment named `pages`, rather than the default `github-pages`.
No environment secrets are needed. Research protection rulesets remain a
milestone 4 task.

## Verify and publish

`operations/expected-settings.yaml` already records all seven action pins,
the platform's `pages: [main]` environment and Pages `build_type: workflow`.
The verifier checks those values, including the exact action allowlist and
environment branch restrictions; unexpected extra allowlist entries fail.
The `/pages` read below also displays the hosting URL and current deployment
status. All 28 configured checks passed on 2026-10-11; rerun them before a
publication or after changing settings to detect drift.

```sh
GITHUB_TOKEN="$(gh auth token)" python -m rp.ops.verify_settings --org we-solve-staging
gh api repos/we-solve-staging/we-solve-staging.github.io/pages --jq '{build_type, html_url, status}'
```

Every verifier check must pass. An unreadable field is not a pass. If the
owner's login cannot read organisation state, ask the owner to refresh the
required scope; do not alter authentication scopes silently.

After local checks and the push-triggered code tests pass, dispatch the full
build and publication for the reviewed research/ledger pair:

```sh
gh workflow run pages.yml --repo we-solve-staging/we-solve-staging.github.io --ref main \
  -f research_sha="$staging_research_sha" -f ledger_sha="$staging_ledger_sha"
gh run list --repo we-solve-staging/we-solve-staging.github.io --workflow pages.yml --limit 5
gh run watch "$staging_run_id" --repo we-solve-staging/we-solve-staging.github.io --exit-status
```

Record the platform/data SHAs, run URL, successful settings report, site size,
largest page payload and rendering diagnostics. Check the live homepage, one
problem from every source collection, a contribution revision, source download,
citations, search and representative reference links. Package sections should
say they are pending; no unavailable Release download should be advertised.

The build preserves the previous Pages deployment when validation fails. To
restore a previous staging publication, dispatch a reviewed platform revision
on `main` with the previously recorded research/ledger pair. Restoring platform
code should use a normal reviewable revert commit; do not force-push history.

## Run the same builder locally

Use a new, empty output directory for each attempt. Keep packages and caches
outside the authoring tree and outside the Pages output:

```sh
python -m rp.site build \
  --work "$staging_work" \
  --out "$staging_output" \
  --base-url https://we-solve-staging.github.io/ \
  --cache-dir "$staging_cache" \
  --packages-dir "$staging_packages" \
  --report "$staging_report"
```

This command includes Pagefind and publication checks. `--no-search` is only
for development and is not used by the staging workflow. The local shell does
not provide the workflow's network namespace; the renderer still processes
source as data and does not fetch linked artifacts.
