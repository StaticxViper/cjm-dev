"""Extract repetitive workflow tasks and supporting evidence from job text."""

from __future__ import annotations

import re
from typing import Any

from utils.jobs import clean_text

# Phrase -> canonical task label
TASK_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"data entr|enter(ing)? data|input(ting)? data|key(ing)? in", re.I), "Enter data into systems or spreadsheets"),
    (re.compile(r"spreadsheet|excel|google sheets", re.I), "Update spreadsheets"),
    (re.compile(r"\bcrm\b|salesforce|hubspot|update (customer|client) record", re.I), "Update CRM records"),
    (re.compile(r"web research|internet research|online research|research (online|websites?)", re.I), "Research information online"),
    (re.compile(r"property (research|records?|information|details)|mls|listing research", re.I), "Research property information"),
    (re.compile(r"lead research|research leads|prospect research", re.I), "Research leads"),
    (re.compile(r"lead generat", re.I), "Generate and qualify leads"),
    (re.compile(r"verif(y|ication)|cross[-\s]?check|validate (data|records?|information)", re.I), "Verify records and information"),
    (re.compile(r"monitor(ing)? (websites?|sites?|portals?|listings?|dashboards?)", re.I), "Monitor websites or portals"),
    (re.compile(r"report generat|generate reports?|prepare reports?|recurring reports?", re.I), "Generate recurring reports"),
    (re.compile(r"document process|process(ing)? documents?|scan(ning)? documents?", re.I), "Process documents"),
    (re.compile(r"invoice process|process(ing)? invoices?", re.I), "Process invoices"),
    (re.compile(r"order process|process(ing)? orders?", re.I), "Process orders"),
    (re.compile(r"product listing|upload(ing)? listings?|post(ing)? listings?|catalog", re.I), "Upload or update product/listings catalogs"),
    (re.compile(r"inventory", re.I), "Check and update inventory records"),
    (re.compile(r"manual (qa|test)|website test|test(ing)? web|quality assurance|bug report", re.I), "Perform repetitive website/QA testing"),
    (re.compile(r"copy(ing)? (data|information) between|transfer(ring)? data", re.I), "Copy data between systems"),
    (re.compile(r"download(ing)?|upload(ing)? (files?|documents?|spreadsheets?)", re.I), "Download/upload files"),
    (re.compile(r"schedul(e|ing)|calendar management|book(ing)? appointments?", re.I), "Handle scheduling/calendar updates"),
    (re.compile(r"email (campaigns?|outreach|follow[-\s]?ups?)|send(ing)? (recurring )?emails?", re.I), "Send recurring emails"),
    (re.compile(r"collect(ing)? (information|data|details)|gather(ing)? (information|data)", re.I), "Collect information from multiple sources"),
    (re.compile(r"compar(e|ing) records?|reconcile|dedup", re.I), "Compare and reconcile records"),
    (re.compile(r"compliance data|claims process", re.I), "Process compliance/claims data entry"),
    (re.compile(r"content (update|upload|entry)|update(ing)? (the )?website", re.I), "Update website or content listings"),
    (re.compile(r"seo|keyword research", re.I), "Perform SEO/keyword research tasks"),
]


def extract_workflow(job: dict[str, Any]) -> dict[str, Any]:
    """Return workflow_tasks and short workflow_evidence from job fields."""
    text = " ".join(
        str(job.get(k) or "")
        for k in (
            "job_title",
            "job_description",
            "responsibilities",
            "requirements",
            "snippet",
        )
    )
    text = clean_text(text)
    tasks: list[str] = []
    evidence: list[str] = []
    for pattern, label in TASK_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        if label not in tasks:
            tasks.append(label)
        start = max(0, match.start() - 40)
        end = min(len(text), match.end() + 80)
        excerpt = clean_text(text[start:end])
        if excerpt and excerpt not in evidence:
            evidence.append(excerpt[:180])
        if len(tasks) >= 8:
            break

    # Title-based fallbacks when description is thin
    title = str(job.get("job_title") or "").lower()
    if not tasks:
        if "data entry" in title:
            tasks.append("Enter data into systems or spreadsheets")
        if "research" in title:
            tasks.append("Research information online")
        if "qa" in title or "tester" in title:
            tasks.append("Perform repetitive website/QA testing")
        if "listing" in title:
            tasks.append("Upload or update product/listings catalogs")
        if "coordinator" in title or "assistant" in title:
            tasks.append("Perform recurring administrative digital tasks")

    return {
        "workflow_tasks": tasks,
        "workflow_evidence": evidence[:5],
    }
