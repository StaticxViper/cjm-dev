import argparse
import csv
import json
import sys
from pathlib import Path

# Add repo root to sys.path
repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))

from crm_mcp import CrmMcpClient
from helper_scripts.utils.logger import setup_logger

logger = setup_logger(
    name="lead-automation",
    console_levels=["INFO", "ERROR", "CRITICAL"]  # Only these show in console, any of them can be removed.
)

KEYWORDS = json.load(open("keywords.json"))

parser = argparse.ArgumentParser(description='Lead Automation')
parser.add_argument('-i/', '--individual', default=False, help='Run individual leads', action='store_true')
parser.add_argument('-b/', '--bulk', default=False, help='Run bulk leads', action='store_true')
args = parser.parse_args()

def extract_real_email(raw_email_field):
    emails = raw_email_field.split(";")
    for e in emails:
        e = e.strip().lower()
        if e and "sentry" not in e and "wixpress" not in e:
            return e
    return ""

def _lead_from_csv_row(row):
    niche_key = KEYWORDS[row["niche_key"]]
    lead = {
        "business_name": row["business_name"],
        "address": row.get("address") or "",
        "phone": row.get("phone_google") or "",
        "email": extract_real_email(row.get("email") or ""),
        "category": niche_key,
        "tags": ["lead_automation", "google-places-api"],
        "score": int(row["lead_score"]),
    }
    if row.get("website"):
        lead["website"] = row["website"]
    if row.get("rating") not in (None, ""):
        lead["rating"] = float(row["rating"])
    if row.get("user_ratings_total") not in (None, ""):
        lead["user_ratings_total"] = int(row["user_ratings_total"])
    return lead


def main():
    logger.critical('Starting Lead Automation...')

    if not (args.individual or args.bulk):
        logger.error("Pass --individual or --bulk.")
        return

    client = CrmMcpClient()
    if not client.api_key:
        logger.error("CRM_MCP_MV_LLC is required to upload leads.")
        return

    with open("leads_output.csv", newline="", encoding="utf-8") as file:
        rows = [_lead_from_csv_row(row) for row in csv.DictReader(file)]

    logger.critical("Sending %d leads to CRM", len(rows))
    uploaded = 0
    for lead in rows:
        logger.info("Business: %s", lead["business_name"])
        client.create_lead(lead)
        uploaded += 1
    logger.critical("Created %d CRM leads", uploaded)


if __name__ == "__main__":
    main()