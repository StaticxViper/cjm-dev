# Script manager

One command that knows every runnable script in this repo. It sets the working directory, `PYTHONPATH`, and environment, then runs the script. Flagged standalone commands still work. Startup menus for the main scripts live here, not in those scripts.

From the repo root:

```bash
python -m scripts.script_manager list
python -m scripts.script_manager info leadgen
python -m scripts.script_manager run leadgen -- --defaults --leadgen-type playwright --state NJ
python -m scripts.script_manager run stock-analyzer
python -m scripts.script_manager validate
python -m scripts.script_manager menu
```

GitHub Actions runs the same manager. Inputs, triggers, sinks, and how to add a script, secret, schedule, or sink are in [script_manager_actions.md](script_manager_actions.md).

From any directory, the repo-root shim does the same thing:

```bash
python path/to/cjm-dev/manage.py list
```

`python -m scripts.script_manager` has to be started with the repo root on `PYTHONPATH` (that is what a shell sitting in the repo root does). The manager then finds the repo from its own file location, so the child script gets the right working directory even if your shell is somewhere else inside the repo. On a terminal, that command with no subcommand opens the menu.

## Commands

Every command accepts `--registry PATH` and `--json`. Human logs go to stderr with the prefix `[script-manager]`. `--json` writes a JSON document to stdout.

| Command | What it does |
|---------|----------------|
| `list [--tag T] [--status S] [--ci]` | Table of name, status, Playwright, CI, tags, description. `--ci` keeps active scripts that are allowed in CI. |
| `info <name> [--ci] [-- args...]` | Metadata, resolved command, cwd, `PYTHONPATH`, and env names marked present or missing. `--ci` applies the CI gates and exits 67 when the script cannot run there. It does not ask for confirmation. |
| `help <name>` | The script's own `--help` when it has argparse. Otherwise the registry description, docs path, and an example. |
| `run <name> [options] [-- args...]` | Everything after `--` is passed through unchanged. |
| `validate [--strict] [--smoke] [--ci-secrets]` | Schema, paths, docs, unregistered `__main__` files, and the env-name table in [the docs index](../README.md). `--ci-secrets` also checks the workflow secrets block. |
| `menu` | Pick a main script, fill in its menu, and queue several runs. The queue runs one script after another. |
| `contract` | Write the CI run contract from the environment. |
| `resolve` | Playwright, timeout, outputs, and the CI gates, without starting the script. |
| `sinks` | Deliver a run summary. A sink failure is recorded and does not change the script exit code. |
| `schedules` | `--due`, `--check`, or `--write` for registry cron entries. |

With no subcommand, a terminal opens `menu`. A pipe still prints usage and exits 2.

## Menu

`menu` is the only place that asks which script to run and which flags to use. Each main script has its own screen:

- Leadgen option 1 asks for free-text niches and keyword strings, then locations. `presets` still offers `keywords.json`. A run is queued as `--free-text`, `--niche`, and `--keywords`. Settings still write `scripts/lead_automation/leadgen_settings.json`. Option 5 is still the configured micro-niche search.
- Opp finder keeps search, presets, and skill toggles. A run is queued as `--preset` or `--employment` / `--keywords` flags. The registry status stays planned, so the queue asks before it runs.
- Clip generator lists ride folders. Montage builder asks for a theme and a count.
- Other main scripts get a flag menu from the registry, or a confirm screen when they take no arguments. Blank answers skip a flag. An extra-args line is there for anything the prompts do not list.

The home screen can add several scripts, remove one, then run the queue. A non-zero exit asks whether to continue. Scripts that require confirmation, and scripts that are not active, ask before they are queued.

These scripts do not get a menu: broken scripts, `api-manager-selftest`, `ci-ping`, the `leadgen-new-business` alias (it is a leadgen choice), `grocery-sync` (same program as `grocery-cli`), and `opp-finder` (not in this checkout).

`python leadgen.py` with no flags asks for business niches and keyword strings, then runs. Opp finder, the clip generator, and the montage builder still exit 2 and point at this menu. `python leadgen.py --defaults ...` and every other flagged command still run on their own. `--niche` and `--keywords` accept the same free text as the prompts.

The ShopRite store picker still waits inside the grocery child after the browser opens. The grocery menu only queues `--set-shoprite-store`.

`info --json` is the shape a workflow can consume:

```json
{
  "name": "stock-analyzer",
  "status": "active",
  "entry": {"type": "path", "path": "scripts/stock_analyzer/stock_analyzer.py"},
  "cwd": ".",
  "command": ["python", "scripts/stock_analyzer/stock_analyzer.py"],
  "needs_playwright_resolved": false,
  "env": {"required_missing": [], "optional_missing": [], "conditional_missing": []},
  "timeout_seconds": 1800,
  "outputs": ["logs/**"],
  "default_outputs": ["artifact"],
  "ci_allowed": true,
  "schedule": {"cron": "0 14 * * 1-5", "tz": "UTC", "confirm": true, "note": "weekdays 14:00 UTC via script_manager_schedule.yml"}
}
```

`list --ci --json` is the list of scripts a CI job is allowed to start.

`info <name> --ci --json` uses the same gates as a CI run (not active, `local_only`, or not `ci_allowed` exits 67) and adds `ok`, `exit_code`, `failure_kind`, and `message`. Confirmation is not required, because `info` does not start the script.

### Run options

| Option | Effect |
|--------|--------|
| `--dry-run` | Print the command, cwd, and env names. Do not start the process. |
| `--timeout SECONDS` | Override the registry timeout. |
| `--env-file PATH` / `--no-dotenv` | Read a different env file, or do not read one. |
| `--non-interactive` / `--interactive` | Detach stdin, or keep prompts. See below. |
| `--yes` / `--confirm` | Required when `confirm_required` is true. On a `--ci` run, also required when the script has any `side_effects`, unless this is a dry run. |
| `--force` | Run a broken, legacy, or planned script. A planned script whose file is not in the checkout still fails. |
| `--no-defaults` | Do not insert `default_args`. |
| `--summary-json PATH` | Write the run summary as JSON. |
| `--github-summary` | Append a short markdown block to `$GITHUB_STEP_SUMMARY` when that variable is set. |
| `--ci` | Refuse a script that is not active, is `local_only`, or is not `ci_allowed` (exit 67). `--force` does not bypass this. |
| `--env-scope declared` | Pass only the script's declared env names plus a safe base set. This is the default when `CI` is `true`, `1`, or `yes`. `--env-scope inherit` keeps the full environment. |
| `--log-file PATH` | Also write the manager's own log. This does not upload anywhere. |

If `CI` is set as above, or stdin is not a terminal, the run is non-interactive unless you pass `--interactive`. Non-interactive mode points stdin at the null device. When you did not pass script args, it appends `non_interactive_args` (leadgen gets `--defaults`). An interactive script that would still prompt exits 69.

Args after `--` are a list, not a shell string. Repeated flags stay repeated: `--city "Cherry Hill" --city Newark` arrives as two `--city` values.

## Registry

`scripts/script_manager/registry.json` is the list of scripts. `registry.schema.json` describes the fields. The checker in `registry.py` is hand-written and uses only the standard library, so the manager does not depend on `jsonschema` (that package is already in `requirements/requirements.txt` for other tools).

To add a script:

1. Run it once by hand and note the working directory, env names, and whether `__main__` prompts or posts somewhere.
2. Add an object under `scripts`. `name` is lowercase words and hyphens. `entry` is either `{"type": "path", "path": "scripts/.../tool.py"}` or `{"type": "module", "module": "package.module"}`. `cwd` is repo-relative (`.` is the repo root).
3. Set `needs_playwright` to `true`, `false`, or `"conditional"`. Conditional entries need `playwright_when_args_any`.
4. Put env **names** in `env.required`, `env.optional`, or `env.conditional`. Never put values in the registry.
5. If the script is not on this branch yet, use `"status": "planned"` and a `status_reason`. `run` refuses it without `--force`, and `--force` still fails when the entry file is missing.
6. Run `python -m scripts.script_manager validate`. Fix errors. `--strict` turns warnings into errors.

`validate` does not warn when a `local_only` script's system dependency is missing from `PATH`. Those scripts are refused in CI, so a runner without `ffmpeg` still passes `--strict`.

`validate` scans each directory in `discover_roots` (by default `scripts/` and `helper_scripts/`) for `if __name__ == "__main__"`. Files listed in `ignore_paths` are skipped (deprecated video tools, the Raspberry Pi updater, the logger example, and the manager itself). Anything else that is not an entry in the registry is a warning. Moving those folders is a `discover_roots` edit. The workflow does not name them.

A conditional token matches when it equals an arg, when `--flag=value` equals an arg, or when `--flag` is followed by the value. The rules do not read saved settings or a script's own argparse defaults. `info` says this. leadgen's default discovery type is `api_manager`, and `--defaults` can also load `leadgen_settings.json`, so `GOOGLE_API_KEY` stays optional unless you actually pass `--leadgen-type=api_manager`. The script still exits on its own when a key it needs is missing.

`opp-finder`, `opp-finder-v2`, and `leadgen-new-business` are `planned`. The v2 package is in this checkout; `run` stays gated until its status is `active`. `--sites` on v2 is a placeholder for "this run needs Chromium". Blog automation, the webhook manager, the JSON formatter, lead ingest, and Lovable automation are `broken` because `from helper_scripts.utils.logger import setup_logger` fails (the logger package has no `__init__.py`). That import is fixed in a separate change. `validate --smoke` imports the broken scripts without running their `__main__` blocks, so a webhook or other side effect does not fire, and prints the traceback. It also runs `--help` for active scripts that support it, with a 30 second cap, `--no-dotenv`, and without the required-env check. A script that calls `load_dotenv` itself, including the logger's upload-on-exit hook, still reads the repo-root `.env` during that `--help`. `--smoke` exits 65 while those imports are still broken.

Apify actors under `scripts/apify-scripts/` are started with the Apify CLI, not this manager. `APIFY_TOKEN` is listed on `api-manager-selftest` so the env table in the docs index has a matching registry name. The selftest does not read that variable.

## Environment

The repo-root `.env` is read with `dotenv_values()`. The manager's own process environment is not modified. Real environment variables win over the file, including when the process value is empty. `--env-file` changes the path. `--no-dotenv` skips the file. Scripts that never call `load_dotenv` (Lovable is one) still receive the file's values from the child environment.

Missing required names, and conditional names whose rule matched, exit 66:

```text
stock-analyzer: missing required env: STOCK_INGEST_TOKEN, PERPLEXITY_API_KEY (set them in .env or the environment).
```

The message lists names. Logs, dry-run output, `info`, the run summary, and `--github-summary` never include values.

`--env-scope declared` (the default when `CI` is true) passes the names the script declares, plus a base set the process needs to start: `PATH`, `PATHEXT`, `HOME`, `USERPROFILE`, `HOMEDRIVE`, `HOMEPATH`, `APPDATA`, `LOCALAPPDATA`, `SYSTEMROOT`, `SYSTEMDRIVE`, `WINDIR`, `COMSPEC`, `TEMP`, `TMP`, `USERNAME`, `USER`, `LANG`, `LC_*`, `PLAYWRIGHT_BROWSERS_PATH`, `CI`, `PYTHON*`, `GITHUB_*`, and `RUNNER_*`.

`PYTHONPATH` is the repo root, then any `pythonpath` entries from the registry, then the existing value. `PYTHONUNBUFFERED` is `1`. The child is `sys.executable`, so the active virtualenv is the one that runs.

## Exit codes

| Code | Meaning |
|------|---------|
| child's code | The process finished. 0 is success. |
| 2 | Manager usage error. |
| 64 | Unknown script. The message includes close name matches. |
| 65 | Registry invalid, or `validate` failed. |
| 66 | Missing required or conditional env names. |
| 67 | Not runnable: planned, broken, or legacy without `--force`; missing entry; missing system dependency; Playwright Chromium missing. Under `--ci`, also not active, `local_only`, or not `ci_allowed`. |
| 68 | `confirm_required` without `--yes`, or a `--ci` run of a script with `side_effects` without `--confirm`. A dry run does not ask. |
| 69 | The script would prompt and this run is non-interactive. |
| 124 | Timed out. The process tree is stopped. |
| 130 | Interrupted. |

A script can exit with one of these numbers itself. The run summary's `failure_kind` is `child_exit` in that case, and one of `unknown_script`, `registry_invalid`, `missing_env`, `not_runnable`, `confirmation_required`, `would_prompt`, `timeout`, `interrupted`, or `cancelled` when the manager stopped first. Success uses `null`. On GitHub, exit 2, 64, and 68 are recorded in `run.json` and the workflow still succeeds. The other non-zero results fail the workflow. Details are in [script_manager_actions.md](script_manager_actions.md).

The summary is one JSON line on stdout. `--summary-json` writes the same object to a file. `outputs` are the registry globs that exist after the run. `duration_s` is `finished_at` minus `started_at`.

On timeout or Ctrl-C the child is started in its own process group (`start_new_session` on Linux and macOS, `CREATE_NEW_PROCESS_GROUP` on Windows). The manager terminates that tree, waits 10 seconds, then kills it. Windows uses `taskkill /T` so grandchildren die with the script.

## Playwright and other dependencies

When the resolved args need Playwright, the manager checks that the package imports and that the Chromium executable from `playwright.chromium.executable_path` exists. If it does not:

```bash
python -m playwright install chromium
```

The manager does not install packages or browsers. `deps.system` (for example `ffmpeg`) is reported by `info` and `validate`, and a normal `run` exits 67 when the command is not on `PATH`.

## Windows

Paths in the registry use forward slashes. The manager resolves them from the repo root, so a drive-letter checkout works. Run from `cmd` or PowerShell with the virtualenv active. `manage.py` is the easy entry when the shell is not already in the repo. Video scripts stay local: they need FFmpeg and the media folder from `MOTO_VIDS_BASE` (default `E:\0. Moto Vids`).
