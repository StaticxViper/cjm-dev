import csv
import json
import sys
from datetime import datetime
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))

from helper_scripts.api_manager import APIManager as api
from helper_scripts.utils.logger.logger import setup_logger

SCRIPT_DIR = Path(__file__).resolve().parent
COMPANIES_FILE = SCRIPT_DIR / "companies.json"
OUTPUT_DIR = SCRIPT_DIR / "output"
CSV_FIELDS = ["name", "headline", "location", "LinkedIn URL", "current company"]

logger = setup_logger(
    name="operation-learn",
    console_levels=["INFO", "ERROR", "CRITICAL"],
)


def profile_name(item):
    name = item.get("fullName") or item.get("name")
    if name:
        return name
    return " ".join(part for part in (item.get("firstName"), item.get("lastName")) if part).strip()


def profile_location(item):
    loc = item.get("location")
    if isinstance(loc, dict):
        parsed = loc.get("parsed") or {}
        return loc.get("linkedinText") or parsed.get("text") or ""
    return loc or ""


def profile_company(item):
    positions = item.get("currentPosition") or item.get("currentPositions") or []
    if isinstance(positions, list) and positions:
        first = positions[0]
        if isinstance(first, dict):
            return first.get("companyName") or ""
        return str(first)
    return ""


def main():
    logger.critical("Starting recruiter scrape...")

    with open(COMPANIES_FILE, encoding="utf-8") as f:
        data = json.load(f)
    companies = data["companies"] if isinstance(data, dict) else data

    OUTPUT_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"recruiters_{timestamp}.csv"
    client = api()
    total = 0

    with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=CSV_FIELDS)
        writer.writeheader()

        for company in companies:
            logger.info("Scraping recruiters at %s", company)
            try:
                items = client.run_apify(
                    actor="LinkedIn Company Employees",
                    input={
                        "companies": [company],
                        "profileScraperMode": "Short ($4 per 1k)",
                        "searchQuery": "recruiter",
                        "maxItems": 200,
                        "companyBatchMode": "one_by_one",
                    },
                )
                if not items:
                    logger.error("No results for %s", company)
                    continue

                for item in items:
                    writer.writerow({
                        "name": profile_name(item),
                        "headline": item.get("headline") or "",
                        "location": profile_location(item),
                        "LinkedIn URL": item.get("linkedinUrl") or "",
                        "current company": profile_company(item),
                    })
                    total += 1
                csvfile.flush()
                logger.info("Got %s profiles from %s", len(items), company)
            except Exception as e:
                logger.error("Failed to scrape %s: %s", company, e)

    logger.critical("Wrote %s recruiters to %s", total, output_path)


if __name__ == "__main__":
    main()
