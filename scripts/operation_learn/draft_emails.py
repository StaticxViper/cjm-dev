import csv
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR / "output"

SENDER_NAME = "[Your name]"
STRONG_TERMS = ("technical recruiter", "engineering recruiter", "tech recruiter", "software recruiter")


def latest_csv():
    files = list(OUTPUT_DIR.glob("recruiters_*.csv"))
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def is_true(value):
    return str(value).strip().lower() == "true"


def first_name(raw_name):
    parts = (raw_name or "").strip().split()
    if not parts:
        return "there"
    cleaned = "".join(ch for ch in parts[0] if ch.isalpha() or ch in "-'")
    if not cleaned:
        return "there"
    return cleaned.capitalize() if cleaned.islower() else cleaned


def company_name(row):
    company = (row.get("current company") or "").strip()
    if company:
        return company
    slug = (row.get("searched_company") or "").rstrip("/").split("/")[-1]
    return slug.replace("-", " ").strip().title() or "your team"


def role_note(row, company):
    # Short mode leaves headline empty, so relevance_score carries the role signal.
    headline = (row.get("headline") or "").lower()
    score = int(row.get("relevance_score") or 0)

    if score >= 3 or any(term in headline for term in STRONG_TERMS):
        return f"since you focus on engineering hiring at {company}"
    if score == 2 or "talent acquisition" in headline:
        return f"since you work on technical talent acquisition at {company}"
    return f"since you recruit for {company}"


def build_draft(row):
    first = first_name(row.get("name"))
    company = company_name(row)
    note = role_note(row, company)

    if is_true(row.get("hiring")):
        ask = (
            "Since you're actively hiring, I'm looking for remote software engineering roles "
            "and would be glad to be considered for anything open."
        )
    else:
        ask = (
            "I'm looking for remote software engineering roles and would be glad to be "
            "considered for anything open on your team."
        )

    # Company names like "Affirm, Inc." already end in a period.
    opener = f"I'm reaching out {note}".rstrip(".") + "."

    subject = f"Software Engineer — {company} openings?"
    body = (
        f"Hi {first},\n\n"
        f"{opener} I'm a software engineer with 5 years of experience, "
        f"a background in software testing and QA, and full-stack work across React/Vite "
        f"and Supabase. {ask} My resume is attached if you'd like to take a look.\n\n"
        f"Thanks,\n{SENDER_NAME}"
    )
    return subject, body


def main():
    source = latest_csv()
    if source is None:
        print("No output in dir")
        return

    print(f"Reading {source.name}")
    with open(source, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    blocks = []
    skipped = 0
    for row in rows:
        if is_true(row.get("needs_review")) or int(row.get("relevance_score") or 0) < 1:
            skipped += 1
            continue

        subject, body = build_draft(row)
        blocks.append(
            f"## {len(blocks) + 1}. {row.get('name', '').strip()} — {company_name(row)}\n\n"
            f"LinkedIn: {row.get('LinkedIn URL', '')}\n\n"
            f"Relevance: {row.get('relevance_score', '')} | Hiring: {row.get('hiring', '')}\n\n"
            f"**Subject:** {subject}\n\n"
            f"{body}"
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"email_drafts_{timestamp}.md"
    header = (
        f"# Recruiter email drafts\n\n"
        f"Source: {source.name}\n\n"
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"Drafts: {len(blocks)} | Skipped (needs review or score < 1): {skipped}\n\n"
        f"Attach your resume manually before sending each one."
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n\n---\n\n".join([header, *blocks]) + "\n")

    print(f"Wrote {len(blocks)} drafts to {output_path}")


if __name__ == "__main__":
    main()
