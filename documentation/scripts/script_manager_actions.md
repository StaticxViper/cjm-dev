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
| `caller` | Optional. Who or what started the run, such as `grok-bot` or `crm-dashboard`. Stored as `trigger.caller` in `run.json`. |

`artifact` is always included.

The manager exits **64** when the name is unknown. It exits **67** when the script is not active, is `local_only`, or is not `ci_allowed`. It exits **68** when confirmation is missing. A dry run does not require confirmation.

## Outcomes and failure emails

GitHub emails the person who triggered a run when that run fails. A refused request is the system working, so it does not fail the run. Every `run.json` has an `outcome`:

| `outcome` | When | Workflow run |
|-----------|------|--------------|
| `success` | The script exited 0. A dry run that passed its checks. | success |
| `rejected` | The request was refused: `unknown_script` (64), `confirmation_required` (68), `not_runnable` because the script is not active or not allowed in CI (67), `would_prompt` (69), a bad contract (`usage`, 2), or the script's own argparse rejected the args (`bad_args`, exit 2 with a `usage:` line). | success, with a notice annotation and the reason in the job summary |
| `failed` | The script exited non-zero, timed out, is missing a required secret (`missing_env`), its entry file is missing, or the manager crashed. | failure (email) |
| `cancelled` | The job was cancelled before the script finished. | cancelled |

`exit_code` and `failure_kind` keep their meaning. Callers that need the result should read `outcome` from `run.json`, a callback, or `status`, not the run conclusion.

The last step of each job, `conclude`, sets the job result from `run.json` after the sinks and artifact upload have run.

`clip-generator` and `montage-builder` stay `local_only`. Broken and planned scripts, including `opp-finder-v2`, exit 67 until their status is `active`. The opp finder PR tests stay in `opp_finder_v2.yml`.

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
  -d '{"event_type":"script-manager-run","client_payload":{"script":"stock-analyzer","args":"","request_id":"abc123","outputs":"artifact,property_portal","confirm":true,"caller":"crm-dashboard"}}'
```

`repository_dispatch` uses event type `script-manager-run`. The same body fields work for an MCP `create`/`dispatch` call. GitHub only starts `repository_dispatch` and `schedule` workflows from the default branch.

`ci-ping` is the read-only sample. It has no side effects, so `confirm` stays false. Its stdout is one JSON object (`{"ok": true, "script": "ci-ping", "args": [...]}`), and the run summary stores that object in `data`.

```bash
gh workflow run script_manager.yml -R StaticxViper/cjm-dev \
  -f script=ci-ping -f request_id=ping-1
```

Grok bot routines use that dispatch API on the bot's own schedule.

Cron comes from each script's `schedule.cron`. The schedule workflow asks the manager who is due, then calls this workflow. A schedule run passes `confirm=true` only when that entry sets `"confirm": true`.

## Find a run from its request_id

A dispatch call returns no run id. Send your own unique `request_id` and look the run up by it. The request_id appears in three places:

- The run name: `script-manager <script> <request_id>`.
- The artifact: `script-manager-<request_id>`, holding `run.json`.
- `run.json` itself, along with `run.url`, which every callback, dashboard post, and email also carries.

```bash
GH_TOKEN=... python -m scripts.script_manager status abc123 --repo StaticxViper/cjm-dev --wait 600 --result --json
```

`status` prints `found`, `run_url`, `status`, `conclusion`, `outcome`, and `artifact_url`. With `--result`, it downloads the artifact and includes `run.json`. With `--wait`, it polls until the run completes. It exits 1 when no run matches. Scheduled runs use `schedule-<script>-<schedule run id>`, so `status` reads the run id from the request_id. The token needs read access to Actions on the repository.

Without the manager:

```bash
gh run list -R StaticxViper/cjm-dev -w script_manager.yml --json databaseId,displayTitle,url,conclusion \
  --jq '.[] | select(.displayTitle | endswith(" abc123"))'
gh run download <run id> -R StaticxViper/cjm-dev -n script-manager-abc123
```

## Concurrency

Runs are grouped by request_id (`script-manager-<request_id>`). Two dispatches of the same script with different request_ids both run, and they can overlap. GitHub keeps only one pending run per concurrency group and cancels the rest without telling the caller. Grouping by script made a quick second dispatch cancel the first.

Reusing a request_id deduplicates. The second run waits for the first, and a third pending duplicate cancels the second. A run cancelled while pending never starts a job, so it sends no callback. `status` reports it with `conclusion: cancelled` and `outcome: cancelled`. A run cancelled after it starts still delivers sinks and uploads `run.json` with `outcome: cancelled`.

The job timeout is the script's `timeout_seconds` plus 15 minutes for setup, capped at 360. The manager's own timeout fires first and records `failure_kind: timeout`.

## What the job does

1. `contract` writes `contract.json` from the environment, or from the dispatch event file.
2. `resolve` returns Playwright, timeout (capped at 360 minutes), output globs, declared env names, and the gates above.
3. Chromium is installed only when resolve says it is needed.
4. `run --from-contract contract.json --ci --non-interactive --json --env-scope declared --summary-json run.json --github-summary`
5. `sinks` delivers the summary. Sink errors are appended to `run.json` and the job summary. When the job was cancelled before `run.json` was written, `sinks --job-status` writes one with `outcome: cancelled` and still delivers it.
6. `conclude` fails the job only when `outcome` is `failed` or `cancelled`.

A refused run still uploads `script-manager-<request_id>`. `contract` or `resolve` writes the summary, the prepare job uploads it, and `conclude` ends the run successfully when the refusal is a rejection. `run.json` then has `request_id`, `exit_code`, `failure_kind` (`unknown_script`, `confirmation_required`, `not_runnable`, `usage`), `outcome`, and `message`. If the manager fails before writing a summary, `run.json` has `failure_kind: manager_error` and `outcome: failed`.

Every `run.json` has:

| Field | Meaning |
|-------|---------|
| `outcome` | `success`, `rejected`, `failed`, or `cancelled`. See [Outcomes and failure emails](#outcomes-and-failure-emails). |
| `trigger` | `event` (`workflow_dispatch`, `repository_dispatch`, or `schedule`), `actor` (the GitHub user that triggered the run), `caller` (the `caller` input or payload field), and `schedule` (the cron line on a scheduled run). |
| `run` | `id`, `attempt`, and `url` of the workflow run. |

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

Dashboard and property-portal URLs use that same allowlist. A missing URL, secret, rejected host, or any response other than 2xx is a sink error. It does not replace the script's exit code.

### Testing sinks

`unittests/script_manager/test_sink_endpoints.py` runs on every pull request. It posts the callback and dashboard sinks over real HTTPS to a local server with a throwaway certificate. It also sends the email sink through SMTP with STARTTLS to a local server. The tests check the signature, the bearer token, the 500 and redirect errors, and that the email has no secret values.

To check the deployed config, dispatch the read-only `ci-ping` once per output, then read `sinks` in its `run.json`:

```bash
gh workflow run script_manager.yml -R StaticxViper/cjm-dev -f script=ci-ping -f request_id=sink-callback-1 \
  -f outputs=callback -f callback_url=https://<allowlisted host>/script-manager
gh workflow run script_manager.yml -R StaticxViper/cjm-dev -f script=ci-ping -f request_id=sink-dashboard-1 -f outputs=dashboard
gh workflow run script_manager.yml -R StaticxViper/cjm-dev -f script=ci-ping -f request_id=sink-email-1 -f outputs=email
python -m scripts.script_manager status sink-email-1 --repo StaticxViper/cjm-dev --wait 300 --result --json
```

Each run should list its sink with `"ok": true`. A sink error names what is missing, such as an unset secret or a host that is not allowlisted.

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

On a scheduled run, the workflow passes `github.event.schedule` (the cron line that fired) to `--due --cron`, and the manager selects the scripts with that exact cron. GitHub often starts scheduled runs late. The old Daily Stock Analysis workflow used the same `0 14 * * 1-5` cron and started anywhere from 17:19 to 23:20 UTC. A clock-based check would find nothing due. If no script uses the cron that fired, the run fails and asks for `schedules --write`. Only active, `ci_allowed` scripts are included.

A manual run of the schedule workflow takes an optional `cron` input and runs the scripts for that line as if it fired. Without it, `--due` falls back to crons that matched in the last 90 minutes.

To check that the schedule fired, look for a `schedule` event on the schedule workflow on a weekday after 14:00 UTC, then look up its run:

```bash
gh run list -R StaticxViper/cjm-dev -w script_manager_schedule.yml -e schedule --limit 5
python -m scripts.script_manager status schedule-stock-analyzer-<run id> --repo StaticxViper/cjm-dev --result --json
```

The job summary of the `due` job lists the cron that fired and the scripts it selected.

## Add a sink

1. Add `scripts/script_manager/sinks/my_sink.py` with `send(run_result, config)`. Raise an error with a short message on failure. Do not print secret values.
2. Add `"my_sink": "scripts.script_manager.sinks.my_sink"` to `sinks` in `registry.json`.
3. Callers pass `outputs=artifact,my_sink`, or set `default_outputs`.

The workflow does not change.
