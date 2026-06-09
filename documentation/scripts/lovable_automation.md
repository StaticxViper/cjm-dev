# Lovable Automation

**Source:** `scripts/lovable_automation/lovable_automation.py`

## Purpose

Automates Lovable site creation via the Lovable REST API: create a project from a prompt, wait for the build, optionally remove the Lovable badge via chat, publish, and return a share link. Includes a credit-threshold guard to stop before burning too many credits.

## Prerequisites

- Python 3.12+
- `httpx`, `python-dotenv`
- Repo-root `.env` with **required** `LOVABLE_API_KEY`
- Optional: `LOVABLE_WORKSPACE_ID`, `LOVABLE_CREDIT_THRESHOLD` (default `5`)

## Configuration

| Source | Description |
|--------|-------------|
| `.env` | API key and optional workspace/threshold |
| `--prompt-file` | Text file containing the build prompt |

## How to run

```bash
cd scripts/lovable_automation
python lovable_automation.py -p "Build a landing page for ..."
python lovable_automation.py --prompt-file ./site_prompt.txt
```

### CLI flags

| Flag | Description |
|------|-------------|
| `-p`, `--prompt` | Inline build prompt |
| `--prompt-file` | Read prompt from file |
| `--description` | Project label in Lovable dashboard |
| `--workspace-id` | Lovable workspace (default: env or first available) |
| `--credit-threshold` | Stop if credits drop below this (default: 5) |
| `--skip-publish` | Build only; return preview URL |
| `--skip-badge-removal` | Skip badge-removal chat step |

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | Runtime error (API failure, invalid key, etc.) |
| `2` | Credit threshold exceeded |

## How it works

1. Load prompt from `--prompt` or `--prompt-file`.
2. Resolve workspace and check remaining credits against threshold.
3. POST `/v1/workspaces/{id}/projects` with `initial_message`.
4. Poll build status until complete or timeout (600 s).
5. Unless `--skip-badge-removal`, send a chat message to hide `#lovable-badge` in CSS.
6. Unless `--skip-publish`, publish and poll until live (300 s timeout).
7. Print share link, project ID, and credit usage.

## Related scripts

- [api_manager.md](../helper_scripts/api_manager.md) — HTTP client (note: `Lovable` may need to be added to `API_KEYS` for `get_api_key` to resolve the key)
