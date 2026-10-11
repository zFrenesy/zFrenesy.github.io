# Intake App (prepared, not created)

The intake bot (ADR 0013) needs its own GitHub App. CLAUDE.md requires the owner's approval before any App is created or any secret is added. Nothing here has been done yet.

## 1. Create the App (owner, in the browser)

Create it under the `we-solve-staging` organisation, installed **only** on `we-solve-staging/research`.

| Setting | Value |
| --- | --- |
| Name | `we-solve-staging-intake` |
| Homepage | `https://we-solve-staging.github.io/` |
| Webhook | Off (workflows drive the App) |
| Repository permissions | Contents: read and write (bot-owned `intake/*` branches only, by code); Issues: read and write; Pull requests: read and write; Metadata: read |
| Everything else | No access |
| Where it can be installed | Only on this account |

It must **not** be the final required-check identity, and must not bypass rulesets on `main` or `automation-ledger` (§7). The Publisher App is separate (M4).

## 2. Store the key (owner approval needed)

```sh
gh secret set INTAKE_APP_PRIVATE_KEY --repo we-solve-staging/research --env intake < intake-app.private-key.pem
```

The `intake` environment already exists and deploys only from `main`. Delete the local key file afterwards.

## 3. Allow the token action

Add `actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1` (v3.2.0) to `selected_actions.patterns_allowed` in `operations/expected-settings.yaml` and to the organisation's allowlist. Then run `python -m rp.ops.verify_settings`.

## 4. Deploy the caller

```sh
python -m rp.contribute.kit --out <research-checkout> --research we-solve-staging/research \
  --platform we-solve-staging/we-solve-staging.github.io --ref <platform-sha> \
  --site https://we-solve-staging.github.io/ --with-intake <APP_ID>
```

Commit (`Update research`) and push to `research:main`. The caller runs on `issues`, `issue_comment`, `pull_request_target` and a daily schedule. It calls the platform's `intake.yml` at the pinned commit.

## 5. Drill

1. From a non-owner account, open the attempt form from a problem page, leaving the scope empty. The bot asks at most three questions.
2. Answer them. The bot opens a publication PR from `intake/issue-<n>`, and the issue shows `intake: queued`.
3. Open a fork PR made with `rp submit`. The bot opens `intake/pr-<n>` with the contributor's commits unchanged and closes the source PR as incorporated.
4. Try `/withdraw` from another account: it is ignored. Then `/withdraw` and `/reopen` from the author.
5. Nothing merges. Publication PRs wait for the M4 gate.

Before deploying, `rp intake dry-run --repo we-solve-staging/research --issue N` shows exactly what the bot would do with the maintainer's own read access.
