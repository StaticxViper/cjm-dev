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
CSV_FIELDS = [
    "name",
    "headline",
    "location",
    "LinkedIn URL",
    "current company",
    "relevance_score",
    "hiring",
    "searched_company",
]

STRONG_TERMS = ("technical recruiter", "engineering recruiter", "tech recruiter", "software recruiter")
OFF_TARGET_TERMS = ("sales recruiter", "nurse recruiter", "retail recruiter", "healthcare recruiter", "hospitality")

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


def relevance_score(item):
    headline = (item.get("headline") or "").lower()

    if any(term in headline for term in OFF_TARGET_TERMS):
        return -5
    if any(term in headline for term in STRONG_TERMS):
        return 3
    if "talent acquisition" in headline and ("tech" in headline or "engineering" in headline):
        return 2
    if "recruiter" in headline or "talent acquisition" in headline:
        return 1
    return 0


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
    seen_urls = set()

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
                        "functionIds": [12],
                        "maxItems": 200,
                        "companyBatchMode": "one_by_one",
                    },
                )
                if not items:
                    logger.error("No results for %s", company)
                    continue

                kept = 0
                for item in items:
                    score = relevance_score(item)
                    if score < 0:
                        continue

                    url = item.get("linkedinUrl") or ""
                    if url and url in seen_urls:
                        continue
                    seen_urls.add(url)

                    writer.writerow({
                        "name": profile_name(item),
                        "headline": item.get("headline") or "",
                        "location": profile_location(item),
                        "LinkedIn URL": url,
                        "current company": profile_company(item),
                        "relevance_score": score,
                        "hiring": item.get("hiring", False),
                        "searched_company": company,
                    })
                    kept += 1
                    total += 1
                csvfile.flush()
                logger.info("Kept %s of %s profiles from %s", kept, len(items), company)
            except Exception as e:
                logger.error("Failed to scrape %s: %s", company, e)

    with open(output_path, newline="", encoding="utf-8") as csvfile:
        rows = list(csv.DictReader(csvfile))

    rows.sort(key=lambda row: (int(row["relevance_score"]), row["hiring"] == "True"), reverse=True)

    with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    logger.critical("Wrote %s recruiters to %s", total, output_path)


if __name__ == "__main__":
    main()
