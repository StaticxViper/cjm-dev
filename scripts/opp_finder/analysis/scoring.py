"""Explainable automation and opportunity scoring."""

from __future__ import annotations

import re
from typing import Any

from utils.normalization import join_list

POSITIVE_SIGNALS: list[tuple[str, int, str]] = [
    (r"data entr", 12, "data entry"),
    (r"spreadsheet|excel|google sheets", 10, "spreadsheet work"),
    (r"\bcrm\b|salesforce|hubspot", 8, "CRM updates"),
    (r"web research|internet research|online research", 12, "web research"),
    (r"property research|property records", 12, "property research"),
    (r"monitor(ing)?", 8, "monitoring"),
    (r"manual (qa|test)|website test|quality assurance", 10, "manual QA"),
    (r"report generat|recurring report", 8, "report generation"),
    (r"document process|invoice process|order process", 8, "document/order processing"),
    (r"product listing|catalog|inventory", 8, "listing/catalog work"),
    (r"lead research|lead generat", 8, "lead research"),
    (r"copy(ing)? data|between systems", 10, "cross-system data copying"),
    (r"verif(y|ication)|data verification", 6, "verification"),
    (r"repetitive|routine|high volume", 8, "repetitive/high-volume work"),
    (r"browser|web portal|websites?", 6, "browser-based work"),
    (r"remote", 3, "remote digital role"),
]

NEGATIVE_SIGNALS: list[tuple[str, int, str]] = [
    (r"forklift|warehouse floor|lifting|physical labor|driver\b|cdl\b", 20, "physical work"),
    (r"nurse|cna\b|patient care|clinical", 18, "clinical/interpersonal care"),
    (r"sales quota|cold call|door[-\s]?to[-\s]?door", 12, "highly interpersonal sales"),
    (r"graphic design|creative director|brand strategist|copywriter", 10, "subjective creative work"),
    (r"must be on[-\s]?site|in[-\s]?person only|relocation required", 12, "physical presence required"),
    (r"security clearance|hipaa therapist|licensed attorney", 8, "sensitive/licensed work"),
]


def _text_blob(job: dict[str, Any]) -> str:
    return " ".join(
        str(job.get(k) or "")
        for k in (
            "job_title",
            "job_description",
            "responsibilities",
            "requirements",
            "workflow_tasks",
            "location",
        )
    ).lower()


def score_automation(job: dict[str, Any]) -> dict[str, Any]:
    """Compute component scores and automation narrative fields."""
    text = _text_blob(job)
    tasks = job.get("workflow_tasks") or []
    if isinstance(tasks, str):
        task_list = [t.strip() for t in tasks.split("|") if t.strip()]
    else:
        task_list = list(tasks)

    score = 35
    positives: list[str] = []
    negatives: list[str] = []
    for pattern, weight, label in POSITIVE_SIGNALS:
        if re.search(pattern, text):
            score += weight
            positives.append(label)
    for pattern, weight, label in NEGATIVE_SIGNALS:
        if re.search(pattern, text):
            score -= weight
            negatives.append(label)

    # Task richness bonus
    score += min(15, len(task_list) * 3)
    score = max(0, min(100, score))

    # Percentage bucket
    if score >= 85:
        pct = "80%+"
    elif score >= 70:
        pct = "60–80%"
    elif score >= 55:
        pct = "40–60%"
    elif score >= 40:
        pct = "20–40%"
    else:
        pct = "0–20%"

    tech = _suggest_technology(text, task_list)
    opportunity = _automation_opportunity(job, task_list, tech)
    reasoning = (
        f"Estimated {pct} because "
        + (
            f"signals include {', '.join(positives[:4])}."
            if positives
            else "few clear repetitive digital signals were found."
        )
        + (
            f" Reduced for: {', '.join(negatives[:3])}."
            if negatives
            else " Exceptions and final verification would likely remain human."
        )
    )

    business_value_bits = []
    if any("data" in t.lower() or "spreadsheet" in t.lower() for t in task_list) or "data entr" in text:
        business_value_bits.append("reduce repetitive data entry")
    if any("research" in t.lower() for t in task_list) or "research" in text:
        business_value_bits.append("increase research throughput")
    if "verif" in text:
        business_value_bits.append("reduce manual errors")
    if "report" in text:
        business_value_bits.append("automate recurring reports")
    if "monitor" in text:
        business_value_bits.append("monitor websites continuously")
    if not business_value_bits:
        business_value_bits.append("reduce repetitive digital labor")
        business_value_bits.append("allow employees to focus on exceptions")

    labor_note = ""
    salary = str(job.get("salary") or "").strip()
    if salary:
        labor_note = f" Labor-cost context (estimate only; from posting): {salary}."

    business_value_score = min(100, 40 + len(business_value_bits) * 10 + (8 if salary else 0))
    urgency_score = 40
    if re.search(r"immediate|asap|urgent|hiring now|start immediately", text):
        urgency_score += 25
    if re.search(r"part[-\s]?time|contract|temporary", text):
        urgency_score += 10
    if str(job.get("posting_date") or ""):
        urgency_score += 5
    urgency_score = min(100, urgency_score)

    implementation_fit = 40
    if any(t in " ".join(tech).lower() for t in ("playwright", "python", "pandas")):
        implementation_fit += 20
    if score >= 55:
        implementation_fit += 15
    if "api" in text:
        implementation_fit += 10
    if negatives:
        implementation_fit -= 10 * min(3, len(negatives))
    implementation_fit = max(0, min(100, implementation_fit))

    # Contactability filled later during enrichment; provisional mid value
    # avoids burying strong workflow leads before company research runs.
    contactability = int(job.get("contactability_score") or 50)

    opportunity_score = int(
        round(
            score * 0.35
            + business_value_score * 0.2
            + contactability * 0.2
            + urgency_score * 0.1
            + implementation_fit * 0.15
        )
    )
    opportunity_score = max(0, min(100, opportunity_score))

    if score >= 70 and task_list:
        qualification_reason = (
            "High qualification because the posting explicitly describes "
            f"{', '.join(task_list[:3])}. These tasks appear structured and potentially suitable "
            "for partial browser/Python automation."
        )
    elif score >= 55:
        qualification_reason = (
            "Moderate qualification: some repetitive digital signals are present "
            f"({', '.join(positives[:3]) or 'general admin/digital work'}), "
            "but evidence is incomplete."
        )
    else:
        qualification_reason = (
            "Low qualification: limited evidence of repetitive digital workflows "
            "that would clearly benefit from software automation."
        )

    return {
        "automation_score": score,
        "business_value_score": business_value_score,
        "contactability_score": contactability,
        "urgency_score": urgency_score,
        "implementation_fit_score": implementation_fit,
        "opportunity_score": opportunity_score,
        "automation_percentage_estimate": pct,
        "automation_reasoning": reasoning + labor_note,
        "automation_opportunity": opportunity,
        "possible_technology": tech,
        "business_value": business_value_bits,
        "qualification_reason": qualification_reason,
        "positive_signals": positives,
        "negative_signals": negatives,
    }


def rescore_with_contactability(analysis: dict[str, Any], contactability: int) -> dict[str, Any]:
    """Recompute opportunity_score after contact enrichment."""
    updated = dict(analysis)
    updated["contactability_score"] = max(0, min(100, int(contactability)))
    updated["opportunity_score"] = max(
        0,
        min(
            100,
            int(
                round(
                    int(updated.get("automation_score") or 0) * 0.35
                    + int(updated.get("business_value_score") or 0) * 0.2
                    + int(updated.get("contactability_score") or 0) * 0.2
                    + int(updated.get("urgency_score") or 0) * 0.1
                    + int(updated.get("implementation_fit_score") or 0) * 0.15
                )
            ),
        ),
    )
    return updated


def _suggest_technology(text: str, tasks: list[str]) -> list[str]:
    tech: list[str] = ["Python"]
    blob = text + " " + " ".join(tasks).lower()
    if any(k in blob for k in ("research", "browser", "website", "portal", "qa", "monitor", "listing")):
        tech.append("Playwright")
    if any(k in blob for k in ("api", "json", "webhook")):
        tech.append("APIs")
    else:
        tech.append("Requests")
    if any(k in blob for k in ("spreadsheet", "csv", "excel", "data entr", "report")):
        tech.append("pandas")
    if any(k in blob for k in ("document", "invoice", "pdf", "scan")):
        tech.append("OCR")
    if any(k in blob for k in ("database", "crm", "records")):
        tech.append("SQLite/PostgreSQL")
    if any(k in blob for k in ("recurring", "daily", "monitor", "schedule")):
        tech.append("scheduled jobs")
    if "email" in blob:
        tech.append("email automation")
    # Keep short / relevant
    return tech[:6]


def _automation_opportunity(job: dict[str, Any], tasks: list[str], tech: list[str]) -> str:
    title = str(job.get("job_title") or "this role").strip()
    if tasks:
        focus = ", ".join(tasks[:3])
    else:
        focus = "repetitive digital/administrative work described in the posting"
    tools = " + ".join(tech[:2]) if tech else "Python"
    return (
        f"The {title} position appears to involve {focus}. "
        f"A {tools} workflow could potentially automate the repetitive collection/"
        f"entry steps while leaving exceptions and final verification to a human."
    )


def serialize_analysis_fields(analysis: dict[str, Any]) -> dict[str, Any]:
    """Flatten list fields for CSV storage."""
    out = dict(analysis)
    for key in ("possible_technology", "business_value", "positive_signals", "negative_signals"):
        if isinstance(out.get(key), list):
            out[key] = join_list(out[key])
    return out
