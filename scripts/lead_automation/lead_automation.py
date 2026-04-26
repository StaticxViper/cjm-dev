import argparse
import csv
import json
import sys
from pathlib import Path

# Add repo root to sys.path
repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))

from shared.api_manager import APIManager as api
from shared.logger import setup_logger
from leadgen import save_results

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

def main():
    logger.critical('Starting Lead Automation...')

    base_url = 'https://bvkgatxfefnsfstwihxu.supabase.co/functions/v1'

    if args.individual:
        lead_endpoint = '/leads-ingest'

        with open("leads_output.csv", newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)

            for row in reader:
                business_name = row["business_name"]
                address = row["address"]
                email_addr = extract_real_email(row["email"])
                website = row["website"]
                phone = row["phone_google"]
                rating = row["rating"]
                user_ratings_total = row["user_ratings_total"]
                score = row["lead_score"]
                niche_key = KEYWORDS[row["niche_key"]]

                logger.critical(f"Business: {business_name}, Email: {email_addr}, Website: {website}, Niche Key: {niche_key}")

                lead_data = {
                "business_name": f"{business_name}",
                "address": f"{address}",
                "phone": f"{phone}",
                "email": f"{email_addr}",
                "website": f"{website}",
                "rating": float(rating),
                "user_ratings_total": int(user_ratings_total),
                "category": niche_key,
                "tags": [
                    "lead_automation",
                    "google-places-api"
                ],
                "score": int(score)
                }
                logger.info(f"Lead Data: {lead_data}")
                api().build_request(base_url=base_url, endpoint=lead_endpoint, json_body=lead_data, api="Lead Ingest", method="POST", timeout=60.0)
    elif args.bulk:
        lead_endpoint = '/leads-ingest-bulk'

        with open("leads_output.csv", newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            
            rows = []
            for row in reader:
                business_name = row["business_name"]
                address = row["address"]
                email_addr = extract_real_email(row["email"])
                website = row["website"]
                phone = row["phone_google"]
                rating = row["rating"]
                user_ratings_total = row["user_ratings_total"]
                score = row["lead_score"]
                niche_key = KEYWORDS[row["niche_key"]]

                rows.append({
                    "business_name": business_name,
                    "phone": phone,
                    "email": email_addr,
                    "category": niche_key,
                    "tags": ["lead_automation", "google-places-api"],
                    "score": int(score)
                })

            logger.info(f"Bulk file saved ... Ingesting leads...")
            api().build_request(base_url=base_url, endpoint=lead_endpoint, json_body=rows, api="Lead Ingest", method="POST", timeout=60.0)
            #logger.info(f"Bulk data: {rows}")


if __name__ == "__main__":
    main()