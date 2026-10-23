# Script Manager on GitHub Actions

One workflow runs any script the Script Manager will accept. It does not list scripts or paths. Resolution, gates, timeouts, Playwright, and sinks come from `python -m scripts.script_manager`.

Workflow: [`.github/workflows/script_manager.yml`](../../.github/workflows/script_manager.yml)

Schedules: [`.github/workflows/script_manager_schedule.yml`](../../.github/workflows/script_manager_schedule.yml)

## Run contract

Every trigger sends the same fields.

| Input | Meaning |
|-------|---------|
| `script` | Registry name. Free text, checked at runtime. |
| `args` | One string. The manager splits it with `shlex`. It is never placed in a `run:` script. |
| `request_id` | Optional. Generated when omitted. It is in the run name and in every sink payload. |
| `outputs` | Comma-separated sink names. When empty, the script's `default_outputs` is used, then `artifact`. |
| `confirm` | Required for `confirm_required` or any `side_effects`. `true` or `false`. |
| `dry_run` | Resolve and validate only. External sinks do not run. |
| `callback_url` | HTTPS URL for the `callback` sink. |

`artifact` is always included.

The manager exits **64** when the name is unknown. It exits **67** when the script is not active, is `local_only`, or is not `ci_allowed`. It exits **68** when confirmation is missing. A dry run does not require confirmation.

`clip-generator` and `montage-builder` stay `local_only`. Broken and planned scripts, including `opp-finder-v2`, exit 67 until their status is `active`. Registry validation, schedule drift, and all unit tests run in `ci.yml` on every pull request.

## Triggers

Manual button, `gh`, and `workflow_dispatch`:

```bash
gh workflow run script_manager.yml -R StaticxViper/cjm-dev \
  -f script=stock-analyzer -f args="" -f request_id=abc123 \
  -f outputs=artifact,dashboard -f confirm=true
```

API, scripts, curl, MCP, and a dashboard button (the token stays on the server):

```bash
curl -X POST \
  -H "Authorization: Bearer $GH_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/StaticxViper/cjm-dev/dispatches \
  -d '{"event_type":"script-manager-run","client_payload":{"script":"stock-analyzer","args":"","request_id":"abc123","outputs":"artifact,property_portal","confirm":true}}'
```

`repository_dispatch` uses event type `script-manager-run`. The same body fields work for an MCP `create`/`dispatch` call. GitHub only starts `repository_dispatch` and `schedule` workflows from the default branch.

`ci-ping` is the read-only sample. It has no side effects, so `confirm` stays false. Its stdout is one JSON object (`{"ok": true, "script": "ci-ping", "args": [...]}`), and the run summary stores that object in `data`.

```bash
gh workflow run script_manager.yml -R StaticxViper/cjm-dev \
  -f script=ci-ping -f request_id=ping-1
```

Grok bot routines use that dispatch API on the bot's own schedule.

Cron comes from each script's `schedule.cron`. The schedule workflow asks the manager who is due, then calls this workflow. A schedule run passes `confirm=true` only when that entry sets `"confirm": true`.

The same script never overlaps itself (`script-manager-<name>`, in-progress runs are not cancelled).

## What the job does

1. `contract` writes `contract.json` from the environment, or from the dispatch event file.
2. `resolve` returns Playwright, timeout (capped at 360 minutes), output globs, declared env names, and the gates above.
3. Chromium is installed only when resolve says it is needed.
4. `run --from-contract contract.json --ci --non-interactive --json --env-scope declared --summary-json run.json --github-summary`
5. `sinks` delivers the summary. Sink errors are appended to `run.json` and the job summary. The job still fails when the script itself failed.

A refused run still uploads `script-manager-<request_id>`. `contract` or `resolve` writes the summary, and the prepare job uploads it when that job fails. `run.json` then has `request_id`, `exit_code`, `failure_kind` (`unknown_script`, `confirmation_required`, `missing_env`, `not_runnable`, `usage`), and `message`.

On a run that starts, `run.json` also has:

| Field | Meaning |
|-------|---------|
| `data` | The script's stdout when the whole stream is one JSON object or array, and it is under 1 MB. Otherwise `null`. |
| `stdout_tail` / `stderr_tail` | The last 8000 bytes of each stream. |
| `output_files` | Contents of declared output files (JSON when the file is an object or array, otherwise text). Capped at 20 files, 200 KB each, 1 MB total. |
| `message` | Why the manager refused the run. Empty when the child started. |

`--env-scope declared` passes each script only the env names it lists, plus a safe base set (`PATH`, `GITHUB_*`, and the rest documented in [script_manager.md](script_manager.md)).

## Sinks

Modules live in `scripts/script_manager/sinks/`. Each one defines `send(run_result, config)`. The `sinks` map in `registry.json` points a name at a module.

| Sink | What it does |
|------|----------------|
| `artifact` | Stages `run.json`, `script-manager.log`, and the script's output files. The workflow uploads `script-manager-<request_id>`. Always on. |
| `dashboard` | POST the summary to `SCRIPT_MANAGER_DASHBOARD_URL` with `Authorization: Bearer` from `CRM_MCP_MV_LLC`. |
| `property_portal` | Signed POST to `SCRIPT_MANAGER_PROPERTY_PORTAL_URL`. |
| `callback` | Signed POST to `callback_url`. |
| `email` | Summary mail through `scripts/email_manager/email_manager.py`. |

Signed posts set `X-Script-Manager-Signature` to the hex HMAC-SHA256 of the raw body, using `SCRIPT_MANAGER_CALLBACK_SECRET`. The URL must be `https`, must not include a username or password, and its host must be an exact match in the repo variable `SCRIPT_MANAGER_CALLBACK_HOSTS` (comma-separated). Anything else is rejected. Redirects are not followed.

Dashboard and property-portal URLs use that same allowlist. A missing URL, secret, or a rejected host is a sink error. It does not replace the script's exit code.

Repo variables:

| Name | Used by |
|------|---------|
| `SCRIPT_MANAGER_CALLBACK_HOSTS` | dashboard, property_portal, callback |
| `SCRIPT_MANAGER_DASHBOARD_URL` | dashboard |
| `SCRIPT_MANAGER_PROPERTY_PORTAL_URL` | property_portal |
| `CRM_MCP_VENTURE` | scripts that declare it |
| `DEFAULT_SHOPRITE_ZIP`, `GROCERY_*` | grocery scripts |

Repo secrets used by sinks, in addition to the script secrets in the workflow block: `SCRIPT_MANAGER_CALLBACK_SECRET`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SCRIPT_MANAGER_EMAIL_FROM`, `SCRIPT_MANAGER_EMAIL_TO`.

## Add a script

1. Add the registry entry as in [script_manager.md](script_manager.md). Set `ci_allowed` to `true` only when it should run on GitHub. Leave `local_only` false.
2. Put every name from `env.required`, `env.optional`, and `env.conditional` into the marked block in `script_manager.yml`.
3. Set `default_outputs` when the default should be more than `artifact`.
4. Run `python -m scripts.script_manager validate --ci-secrets`.

No workflow edit is required beyond that secrets block when the script only uses secrets that are already listed. A pull request that marks a script `ci_allowed` without listing a new name fails `validate --ci-secrets`.

Side effects still need `confirm=true` on the dispatch.

## Add a secret

1. Create the secret or variable in the repository settings.
2. Add a line inside `# script-manager:secrets:begin` / `# script-manager:secrets:end`:

```yaml
NEW_API_KEY: ${{ secrets.NEW_API_KEY }}
```

3. Declare that name on the script. `validate --ci-secrets` fails while the line is missing.

GitHub cannot read a secret by a dynamic name, so the block is the full list. Declared scope still filters what the child process sees.

## Add a schedule

On the script:

```json
"schedule": {"cron": "0 14 * * 1-5", "tz": "UTC", "confirm": false}
```

`confirm` must be `true` for an unattended run of a script that has side effects. Otherwise the scheduled run exits 68.

Then:

```bash
python -m scripts.script_manager schedules --write
python -m scripts.script_manager schedules --check
```

`--write` rewrites the cron block in `script_manager_schedule.yml`. `--check` fails when that block drifts. Commit the workflow file with the registry change.

`--due` lists scripts whose cron matched in the last 90 minutes. That grace covers a delayed GitHub schedule. Only active, `ci_allowed` scripts are included.

## Add a sink

1. Add `scripts/script_manager/sinks/my_sink.py` with `send(run_result, config)`. Raise an error with a short message on failure. Do not print secret values.
2. Add `"my_sink": "scripts.script_manager.sinks.my_sink"` to `sinks` in `registry.json`.
3. Callers pass `outputs=artifact,my_sink`, or set `default_outputs`.

The workflow does not change.
