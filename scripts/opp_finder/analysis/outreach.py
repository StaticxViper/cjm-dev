"""Personalized outreach drafts and demo concepts (never auto-sent)."""

from __future__ import annotations

from typing import Any

from utils.normalization import join_list


def generate_outreach(job: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, str]:
    """Build subject/message/demo_concept from evidence in the job record."""
    cfg = config or {}
    sender = ((cfg.get("outreach") or {}).get("sender_name") or "CJ").strip()
    title = str(job.get("job_title") or "open role").strip()
    name = str(job.get("recommended_contact_name") or "").strip()
    greeting = f"Hi {name}," if name else "Hi,"

    tasks = job.get("workflow_tasks") or []
    if isinstance(tasks, str):
        task_list = [t.strip() for t in tasks.split("|") if t.strip()]
    else:
        task_list = [str(t).strip() for t in tasks if str(t).strip()]

    specific = task_list[0] if task_list else "repetitive research/data-entry work"
    workflow = join_list(task_list[:3], sep=", ") if task_list else specific

    values = job.get("business_value") or []
    if isinstance(values, str):
        value_list = [v.strip() for v in values.split("|") if v.strip()]
    else:
        value_list = [str(v).strip() for v in values if str(v).strip()]
    benefit = value_list[0] if value_list else "reduce repetitive manual work"

    subject = f"Potential automation opportunity for your {title} workflow"
    message = (
        f"{greeting}\n\n"
        f"I came across your {title} opening and noticed that the role involves {specific}.\n\n"
        "I build small Python/browser-automation tools that can handle repetitive research, "
        "data-entry, and browser workflows while leaving exceptions and final review to a person.\n\n"
        f"Based on the responsibilities in the posting, it looks like {workflow} could potentially "
        f"be automated to help {benefit}.\n\n"
        "If that is something your team is dealing with, I can put together a small proof of concept "
        "showing what could be automated.\n\n"
        f"Best,\n{sender}"
    )

    demo = generate_demo_concept(job, task_list)
    return {
        "outreach_subject": subject,
        "outreach_message": message,
        "demo_concept": demo,
    }


def generate_demo_concept(job: dict[str, Any], task_list: list[str] | None = None) -> str:
    """Describe a tiny, realistic proof-of-concept tied to the workflow."""
    tasks = task_list
    if tasks is None:
        raw = job.get("workflow_tasks") or []
        if isinstance(raw, str):
            tasks = [t.strip() for t in raw.split("|") if t.strip()]
        else:
            tasks = [str(t).strip() for t in raw if str(t).strip()]

    title = str(job.get("job_title") or "").lower()
    blob = " ".join(tasks).lower() + " " + title

    if "property" in blob:
        return (
            "Create a Playwright tool that accepts a CSV of property addresses, visits specified "
            "public sources, extracts relevant property information, and outputs a completed CSV "
            "for human verification."
        )
    if "qa" in blob or "test" in blob:
        return (
            "Build a small Playwright suite that opens a short list of target pages/flows, "
            "checks key UI states, and writes a CSV/HTML report of pass/fail results for review."
        )
    if "listing" in blob or "catalog" in blob or "product" in blob:
        return (
            "Build a Python script that reads product rows from a CSV, opens the target listing "
            "portal with Playwright where needed, fills structured fields, and exports a results "
            "log for human approval before publishing."
        )
    if "lead" in blob:
        return (
            "Create a Playwright + pandas workflow that takes a seed list of targets, gathers "
            "publicly available business details from approved sources, and writes a clean lead CSV."
        )
    if "monitor" in blob:
        return (
            "Create a scheduled Playwright checker that visits a small set of URLs, records "
            "visible changes/status, and emails a concise digest when something changes."
        )
    if "invoice" in blob or "document" in blob:
        return (
            "Build a Python pipeline that ingests sample documents/PDFs, extracts structured fields "
            "(with OCR if needed), and outputs a reviewable CSV/JSON before any system update."
        )
    return (
        "Build a small Python + Playwright proof of concept that performs the most repetitive "
        f"steps described for this role"
        + (f" ({tasks[0]})" if tasks else "")
        + " on a tiny sample, then exports results to CSV for human review."
    )
