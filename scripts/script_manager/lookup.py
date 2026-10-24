"""Find a Script Manager run from the request_id the caller already has.

GitHub's dispatch APIs do not return a workflow run id. The run name contains
the request_id, and the artifact is named script-manager-<request_id>.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

API = "https://api.github.com"


class LookupError(Exception):
    pass


def artifact_name(request_id: str) -> str:
    return f"script-manager-{request_id}"


def commands(repo: str, request_id: str) -> dict[str, str]:
    owner_repo = repo or "OWNER/REPO"
    name = artifact_name(request_id)
    return {
        "runs": (
            f"gh run list -R {owner_repo} --workflow script_manager.yml "
            f"--json databaseId,displayTitle,url,status,conclusion,createdAt "
            f"--jq '.[] | select(.displayTitle | split(\" \") | index(\"{request_id}\"))'"
        ),
        "artifact": (
            f"gh api -H \"Accept: application/vnd.github+json\" "
            f"\"/repos/{owner_repo}/actions/artifacts?name={name}&per_page=20\""
        ),
    }


def lookup(request_id: str, repo: str | None = None, *, token: str | None = None, per_page: int = 30, opener=None) -> dict:
    """Return matching runs and artifacts. API errors stay in the result."""
    chosen_repo = (repo or os.environ.get("GITHUB_REPOSITORY") or "").strip()
    secret = token if token is not None else (
        os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    )
    result = {
        "request_id": request_id,
        "repo": chosen_repo or None,
        "artifact": artifact_name(request_id),
        "commands": commands(chosen_repo, request_id),
        "runs": [],
        "artifacts": [],
        "api_error": None,
    }
    if not chosen_repo:
        result["api_error"] = "set --repo OWNER/NAME or GITHUB_REPOSITORY to query the API"
        return result
    fetch = opener or _open
    try:
        runs_url = (
            f"{API}/repos/{chosen_repo}/actions/workflows/script_manager.yml/runs"
            f"?per_page={per_page}"
        )
        artifacts_url = (
            f"{API}/repos/{chosen_repo}/actions/artifacts"
            f"?name={artifact_name(request_id)}&per_page={per_page}"
        )
        runs_payload = fetch(runs_url, secret)
        artifacts_payload = fetch(artifacts_url, secret)
    except LookupError as exc:
        result["api_error"] = str(exc)
        return result
    result["runs"] = matching_runs(runs_payload, request_id)
    result["artifacts"] = matching_artifacts(artifacts_payload, request_id)
    return result


def matching_runs(payload: dict, request_id: str) -> list[dict]:
    found = []
    for run in payload.get("workflow_runs") or []:
        title = str(run.get("display_title") or run.get("name") or "")
        if request_id not in title.split():
            continue
        found.append(
            {
                "id": run.get("id"),
                "url": run.get("html_url"),
                "status": run.get("status"),
                "conclusion": run.get("conclusion"),
                "event": run.get("event"),
                "title": title,
                "created_at": run.get("created_at"),
            }
        )
    return found


def matching_artifacts(payload: dict, request_id: str) -> list[dict]:
    name = artifact_name(request_id)
    found = []
    for item in payload.get("artifacts") or []:
        if item.get("name") != name:
            continue
        found.append(
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "expired": item.get("expired"),
                "size_in_bytes": item.get("size_in_bytes"),
                "created_at": item.get("created_at"),
                "workflow_run_id": (item.get("workflow_run") or {}).get("id"),
            }
        )
    return found


def _open(url: str, token: str) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "script-manager",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        raise LookupError(f"GitHub API HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise LookupError(f"GitHub API request failed: {exc.reason}") from exc
