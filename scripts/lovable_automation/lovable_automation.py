"""
Lovable site automation via the Lovable REST API.

Required env (.env at repo root):
    LOVABLE_API_KEY=lov_your_key_here

Optional env:
    LOVABLE_WORKSPACE_ID=
    LOVABLE_CREDIT_THRESHOLD=5

Usage:
    python lovable_automation.py -p "Build a landing page for ..."
    python lovable_automation.py --prompt-file ./site_prompt.txt --credit-threshold 10
"""

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))

from helper_scripts.api_manager import APIManager as api
from helper_scripts.utils.logger import setup_logger

LOVABLE_BASE_URL = "https://api.lovable.dev"
POLL_INTERVAL_SEC = 5
BUILD_TIMEOUT_SEC = 600
PUBLISH_TIMEOUT_SEC = 300

BADGE_REMOVAL_PROMPT = (
    "Add to the global CSS: #lovable-badge { display: none !important; }"
)

logger = setup_logger(
    name="lovable-automation",
    console_levels=["INFO", "ERROR", "CRITICAL"],
)


class CreditThresholdError(Exception):
    """Raised when remaining credits fall below the configured threshold."""


class LovableAutomation:
    def __init__(self, workspace_id: Optional[str], credit_threshold: int):
        self.client = api()
        self.workspace_id = workspace_id or os.getenv("LOVABLE_WORKSPACE_ID") or None
        self.credit_threshold = credit_threshold
        self.credits_start: Optional[int] = None
        self._workspace_cache: Optional[Dict[str, Any]] = None

    def _request(
        self,
        endpoint: str,
        method: str = "GET",
        json_body: Optional[Dict[str, Any]] = None,
        timeout: float = 60.0,
    ) -> Dict[str, Any]:
        try:
            return self.client.build_request(
                base_url=LOVABLE_BASE_URL,
                endpoint=endpoint,
                method=method,
                json_body=json_body,
                api="Lovable",
                timeout=timeout,
            )
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (401, 403):
                raise RuntimeError("Invalid or missing Lovable API key.") from exc
            raise RuntimeError(f"Lovable API error {status}: {exc.response.text}") from exc

    def list_workspaces(self) -> list:
        result = self._request("/v1/workspaces")
        workspaces = result.get("workspaces", result if isinstance(result, list) else [])
        if not workspaces:
            raise RuntimeError("No workspaces found for this API key.")
        return workspaces

    def get_workspace(self) -> Dict[str, Any]:
        if self._workspace_cache:
            return self._workspace_cache

        workspaces = self.list_workspaces()
        if self.workspace_id:
            for ws in workspaces:
                if ws.get("id") == self.workspace_id:
                    self._workspace_cache = ws
                    return ws
            raise RuntimeError(f"Workspace not found: {self.workspace_id}")

        self._workspace_cache = workspaces[0]
        self.workspace_id = self._workspace_cache.get("id")
        logger.info(f"Using workspace: {self._workspace_cache.get('name')} ({self.workspace_id})")
        return self._workspace_cache

    @staticmethod
    def get_remaining_credits(workspace: Dict[str, Any]) -> Optional[int]:
        candidates = [
            workspace.get("credits_remaining"),
            workspace.get("creditsRemaining"),
        ]
        credits = workspace.get("credits")
        if isinstance(credits, dict):
            candidates.extend([
                credits.get("remaining"),
                credits.get("balance"),
                credits.get("available"),
            ])
        plan = workspace.get("plan")
        if isinstance(plan, dict):
            candidates.extend([
                plan.get("credits_remaining"),
                plan.get("creditsRemaining"),
                plan.get("remaining_credits"),
            ])

        for value in candidates:
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    continue
        return None

    def refresh_credits(self) -> Optional[int]:
        workspaces = self.list_workspaces()
        ws_id = self.workspace_id or (workspaces[0].get("id") if workspaces else None)
        for ws in workspaces:
            if ws.get("id") == ws_id:
                self._workspace_cache = ws
                remaining = self.get_remaining_credits(ws)
                logger.info(f"Credits remaining: {remaining}")
                return remaining
        return None

    def assert_credits(self) -> int:
        remaining = self.refresh_credits()
        if remaining is None:
            logger.info("Could not parse credit balance; continuing without credit guard.")
            return -1
        if self.credits_start is None:
            self.credits_start = remaining
        if remaining < self.credit_threshold:
            used = (self.credits_start - remaining) if self.credits_start is not None else None
            msg = f"Credits ({remaining}) below threshold ({self.credit_threshold})"
            if used is not None:
                msg += f"; used ~{used} this run"
            raise CreditThresholdError(msg)
        return remaining

    def create_project(self, description: str, prompt: str) -> Dict[str, Any]:
        ws = self.get_workspace()
        ws_id = ws["id"]
        body = {
            "description": description,
            "initial_message": prompt,
        }
        result = self._request(
            f"/v1/workspaces/{ws_id}/projects",
            method="POST",
            json_body=body,
            timeout=120.0,
        )
        project = result.get("project", result)
        project_id = project.get("id")
        if not project_id:
            raise RuntimeError(f"Project creation did not return an id: {result}")
        logger.critical(f"Created project: {project_id}")
        return project

    def get_project(self, project_id: str) -> Dict[str, Any]:
        result = self._request(f"/v1/projects/{project_id}")
        return result.get("project", result)

    def wait_for_project_ready(self, project_id: str) -> Dict[str, Any]:
        deadline = time.time() + BUILD_TIMEOUT_SEC
        last_status = None
        while time.time() < deadline:
            project = self.get_project(project_id)
            status = (project.get("status") or "").lower()
            last_status = status
            if status in ("completed", "ready", "idle", "done"):
                logger.critical(f"Project ready (status={status})")
                return project
            if status in ("failed", "error"):
                raise RuntimeError(f"Project build failed (status={status})")
            if status not in ("in_progress", "building", "pending", ""):
                logger.info(f"Project status: {status}")
            time.sleep(POLL_INTERVAL_SEC)
        raise RuntimeError(f"Timed out waiting for project build (last status={last_status})")

    def send_chat(self, project_id: str, message: str) -> Dict[str, Any]:
        return self._request(
            f"/v1/projects/{project_id}/messages",
            method="POST",
            json_body={"message": message},
            timeout=120.0,
        )

    def remove_lovable_popup(self, project_id: str) -> Dict[str, Any]:
        logger.critical("Removing Lovable badge via follow-up prompt...")
        self.send_chat(project_id, BADGE_REMOVAL_PROMPT)
        return self.wait_for_project_ready(project_id)

    def publish_project(self, project_id: str) -> Dict[str, Any]:
        return self._request(
            f"/v1/projects/{project_id}/deployments",
            method="POST",
            json_body={},
            timeout=120.0,
        )

    def wait_for_published_url(self, project_id: str) -> Dict[str, Any]:
        deadline = time.time() + PUBLISH_TIMEOUT_SEC
        while time.time() < deadline:
            project = self.get_project(project_id)
            url = self.resolve_share_link(project, prefer_live=True)
            if url and self._is_live_url(url, project):
                logger.critical(f"Published: {url}")
                return project
            time.sleep(POLL_INTERVAL_SEC)
        project = self.get_project(project_id)
        logger.info("Publish poll timed out; returning best available URL.")
        return project

    @staticmethod
    def _is_live_url(url: str, project: Dict[str, Any]) -> bool:
        live_fields = (
            project.get("live_url"),
            project.get("liveUrl"),
            project.get("published_url"),
            project.get("publishedUrl"),
            project.get("url"),
        )
        return url in {v for v in live_fields if v}

    @staticmethod
    def resolve_share_link(project: Dict[str, Any], prefer_live: bool = False) -> Optional[str]:
        live_candidates = [
            project.get("live_url"),
            project.get("liveUrl"),
            project.get("published_url"),
            project.get("publishedUrl"),
            project.get("url"),
        ]
        preview_candidates = [
            project.get("preview_url"),
            project.get("previewUrl"),
        ]
        candidates = live_candidates if prefer_live else live_candidates + preview_candidates
        for value in candidates:
            if value:
                return value
        project_id = project.get("id")
        if project_id:
            return f"https://lovable.dev/projects/{project_id}"
        return None

    def run(
        self,
        prompt: str,
        description: Optional[str] = None,
        skip_publish: bool = False,
        skip_badge_removal: bool = False,
    ) -> Dict[str, Any]:
        if not os.getenv("LOVABLE_API_KEY"):
            raise RuntimeError("LOVABLE_API_KEY is not set. Add it to your .env file.")

        desc = description or prompt[:80].strip()
        self.assert_credits()

        project = self.create_project(desc, prompt)
        project_id = project["id"]
        project = self.wait_for_project_ready(project_id)
        self.assert_credits()

        if not skip_badge_removal:
            project = self.remove_lovable_popup(project_id)
            self.assert_credits()

        if not skip_publish:
            self.publish_project(project_id)
            project = self.wait_for_published_url(project_id)
            self.assert_credits()

        share_link = self.resolve_share_link(project, prefer_live=not skip_publish)
        remaining = self.refresh_credits()
        used = None
        if self.credits_start is not None and remaining is not None:
            used = self.credits_start - remaining

        return {
            "share_link": share_link,
            "project_id": project_id,
            "credits_remaining": remaining,
            "credits_used": used,
        }


def parse_args() -> argparse.Namespace:
    default_threshold = int(os.getenv("LOVABLE_CREDIT_THRESHOLD", "5"))
    parser = argparse.ArgumentParser(description="Create Lovable sites from a prompt.")
    parser.add_argument("-p", "--prompt", help="Detailed prompt for the site to build")
    parser.add_argument("--prompt-file", help="Read prompt from a file")
    parser.add_argument("--description", help="Project label in Lovable dashboard")
    parser.add_argument("--workspace-id", default=os.getenv("LOVABLE_WORKSPACE_ID"))
    parser.add_argument("--credit-threshold", type=int, default=default_threshold)
    parser.add_argument("--skip-publish", action="store_true", help="Build only; return preview URL")
    parser.add_argument("--skip-badge-removal", action="store_true", help="Skip Lovable badge removal chat")
    return parser.parse_args()


def load_prompt(args: argparse.Namespace) -> str:
    if args.prompt_file:
        return Path(args.prompt_file).read_text(encoding="utf-8").strip()
    if args.prompt:
        return args.prompt.strip()
    raise SystemExit("Provide --prompt or --prompt-file.")


def main() -> int:
    args = parse_args()
    prompt = load_prompt(args)

    automation = LovableAutomation(
        workspace_id=args.workspace_id,
        credit_threshold=args.credit_threshold,
    )

    try:
        result = automation.run(
            prompt=prompt,
            description=args.description,
            skip_publish=args.skip_publish,
            skip_badge_removal=args.skip_badge_removal,
        )
    except CreditThresholdError as exc:
        logger.error(str(exc))
        return 2
    except RuntimeError as exc:
        logger.error(str(exc))
        return 1

    print(f"Share link: {result['share_link']}")
    print(f"Project ID: {result['project_id']}")
    if result["credits_remaining"] is not None:
        used_msg = f" (used ~{result['credits_used']} this run)" if result["credits_used"] is not None else ""
        print(f"Credits remaining: {result['credits_remaining']}{used_msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
