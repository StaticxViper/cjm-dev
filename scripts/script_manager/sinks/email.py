"""Email a short run summary. The body never includes env values."""

from __future__ import annotations

from scripts.email_manager.email_manager import build_email, send_email
from scripts.script_manager.sinks import SinkError


def send(run_result: dict, config: dict) -> None:
    env = config["env"]
    host = (env.get("SMTP_HOST") or "").strip()
    sender = (env.get("SCRIPT_MANAGER_EMAIL_FROM") or "").strip()
    recipient = (env.get("SCRIPT_MANAGER_EMAIL_TO") or "").strip()
    password = env.get("SMTP_PASSWORD") or ""
    username = (env.get("SMTP_USERNAME") or sender).strip()
    port_text = (env.get("SMTP_PORT") or "587").strip()
    if not host or not sender or not recipient or not password:
        raise SinkError("email sink is missing SMTP_HOST, SMTP_PASSWORD, SCRIPT_MANAGER_EMAIL_FROM, or SCRIPT_MANAGER_EMAIL_TO")
    try:
        port = int(port_text)
    except ValueError as exc:
        raise SinkError("SMTP_PORT must be an integer") from exc
    recipients = [part.strip() for part in recipient.split(",") if part.strip()]
    name = run_result.get("name") or "script"
    request_id = run_result.get("request_id") or ""
    outcome = run_result.get("outcome") or ""
    trigger = run_result.get("trigger") or {}
    run = run_result.get("run") or {}
    lines = [
        f"script: {name}",
        f"request_id: {request_id}",
        f"outcome: {outcome}",
        f"exit_code: {run_result.get('exit_code')}",
        f"failure_kind: {run_result.get('failure_kind')}",
        f"duration_s: {run_result.get('duration_s')}",
        f"dry_run: {run_result.get('dry_run')}",
        f"trigger: {trigger.get('event')}",
    ]
    if trigger.get("caller"):
        lines.append(f"caller: {trigger.get('caller')}")
    if run.get("url"):
        lines.append(f"run_url: {run.get('url')}")
    if run_result.get("message"):
        lines.append(f"message: {run_result.get('message')}")
    missing = run_result.get("env_missing") or []
    if missing:
        lines.append("env_missing: " + ", ".join(missing))
    message = build_email(
        sender=sender,
        recipients=recipients,
        subject=" ".join(part for part in ("script-manager", name, outcome, request_id) if part),
        body_text="\n".join(lines) + "\n",
    )
    send_email(host, port, username, password, recipients, message)
