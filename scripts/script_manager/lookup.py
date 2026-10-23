"""Find the Script Manager workflow run for a request_id.

A dispatch does not return a run id. Every run carries the request_id in two
places: the run name (``script-manager <script> <request_id>``) and the
artifact name (``script-manager-<request_id>``). Scheduled runs use
``schedule-<script>-<run_id>``, so the run id is read straight from the
request_id.
"""

from __future__ import annotations

import io
import json
import re
import time
import zipfile

API = "https://api.github.com"
WORKFLOW_FILE = "script_manager.yml"
SCHEDULE_REQUEST_RE = re.compile(r"^schedule-[a-z0-9][a-z0-9-]*-(\d+)$")
RUN_NAME_PREFIX = "script-manager "
PAGE_SIZE = 100
MAX_PAGES = 3


class GitHubLookupError(Exception):
    pass


class GitHub:
    def __init__(self, repo: str, token: str | None, api: str = API) -> None:
        self.repo = repo
        self.token = token
        self.api = api.rstrip("/")

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def get_json(self, path: str, params: dict | None = None) -> dict:
        import httpx

        response = httpx.get(f"{self.api}{path}", params=params, headers=self._headers(), timeout=30.0)
        if response.status_code == 404:
            return {}
        if response.status_code >= 400:
            raise GitHubLookupError(f"GitHub API {response.status_code} for {path}")
        return response.json()

    def get_bytes(self, url: str) -> bytes:
        import httpx

        response = httpx.get(url, headers=self._headers(), timeout=60.0, follow_redirects=True)
        if response.status_code >= 400:
            raise GitHubLookupError(f"GitHub API {response.status_code} downloading the artifact")
        return response.content


def artifact_name(request_id: str) -> str:
    return f"script-manager-{request_id}"


def run_name_matches(title: str, request_id: str) -> bool:
    parts = (title or "").split()
    return bool(parts) and title.startswith(RUN_NAME_PREFIX) and parts[-1] == request_id


def find_run(client: GitHub, request_id: str) -> dict | None:
    match = SCHEDULE_REQUEST_RE.fullmatch(request_id)
    if match:
        run = client.get_json(f"/repos/{client.repo}/actions/runs/{match.group(1)}")
        return run or None
    for page in range(1, MAX_PAGES + 1):
        body = client.get_json(
            f"/repos/{client.repo}/actions/workflows/{WORKFLOW_FILE}/runs",
            {"per_page": PAGE_SIZE, "page": page},
        )
        runs = body.get("workflow_runs") or []
        for run in runs:
            if run_name_matches(run.get("display_title") or run.get("name") or "", request_id):
                return run
        if len(runs) < PAGE_SIZE:
            break
    return None


def find_artifact(client: GitHub, run_id, request_id: str) -> dict | None:
    body = client.get_json(f"/repos/{client.repo}/actions/runs/{run_id}/artifacts", {"per_page": 100})
    wanted = artifact_name(request_id)
    for item in body.get("artifacts") or []:
        if item.get("name") == wanted:
            return item
    return None


def read_run_json(client: GitHub, artifact: dict) -> dict | None:
    url = artifact.get("archive_download_url")
    if not url or artifact.get("expired"):
        return None
    with zipfile.ZipFile(io.BytesIO(client.get_bytes(url))) as archive:
        try:
            raw = archive.read("run.json")
        except KeyError:
            return None
    data = json.loads(raw.decode("utf-8"))
    return data if isinstance(data, dict) else None


def lookup(client: GitHub, request_id: str, *, fetch_result: bool = False) -> dict:
    run = find_run(client, request_id)
    report = {
        "request_id": request_id,
        "found": run is not None,
        "run_id": None,
        "run_url": None,
        "event": None,
        "status": None,
        "conclusion": None,
        "created_at": None,
        "artifact": artifact_name(request_id),
        "artifact_url": None,
        "outcome": None,
        "result": None,
    }
    if run is None:
        return report
    report.update(
        {
            "run_id": run.get("id"),
            "run_url": run.get("html_url"),
            "event": run.get("event"),
            "status": run.get("status"),
            "conclusion": run.get("conclusion"),
            "created_at": run.get("created_at"),
        }
    )
    if run.get("status") != "completed":
        return report
    if run.get("conclusion") == "cancelled":
        report["outcome"] = "cancelled"
    artifact = find_artifact(client, run.get("id"), request_id)
    if artifact is not None:
        report["artifact_url"] = f"{run.get('html_url')}/artifacts/{artifact.get('id')}"
        if fetch_result:
            result = read_run_json(client, artifact)
            report["result"] = result
            if result and result.get("outcome"):
                report["outcome"] = result["outcome"]
    return report


def wait_for(client: GitHub, request_id: str, *, timeout_s: float, interval_s: float = 10.0, fetch_result: bool = False, sleep=time.sleep, clock=time.monotonic) -> dict:
    """Poll until the run exists and completes, or until timeout_s passes."""
    deadline = clock() + timeout_s
    while True:
        report = lookup(client, request_id, fetch_result=fetch_result)
        if report["found"] and report["status"] == "completed":
            return report
        if clock() >= deadline:
            return report
        sleep(interval_s)
