import csv
import email
import sys
from pathlib import Path
#import pandas as pd

# Add repo root to sys.path
repo_root = Path(__file__).resolve().parents[2]  # stock_analyzer.py -> stock_analyzer/ -> scripts/ -> repo_root
sys.path.insert(0, str(repo_root))

from scripts.email_manager import email_manager
from shared.logger import setup_logger

logger = setup_logger(
    name="lead-automation",
    console_levels=["ERROR", "CRITICAL"]  # Only these show in console, any of them can be removed.
)


def mark_contacted_and_remove_from_csv(email_addr, csv_path="leads_output.csv"):
    email_addr = (email_addr or "").strip().lower()
    if not email_addr:
        return

    # Append to contacted.txt
    with open("contacted.txt", "a", encoding="utf-8") as f:
        f.write(email_addr + "\n")

    # Remove from CSV safely
    try:
        df = pd.read_csv(csv_path)
    except Exception:
        return

    if df.empty or "email" not in df.columns:
        return

    df["email"] = df["email"].fillna("").astype(str).str.lower()
    df = df[df["email"] != email_addr]
    df.to_csv(csv_path, index=False)


def build_email_template(business_name, address, website, rating, landing_page_link):
    website_status = "no website" if website.strip() == "" else "a website that could use improvement"

    subject = f"Quick idea for {business_name} website"

    body = f"""Hello,

            I hope all is well with you!

            I came across {business_name} while looking at businesses around your location ({address}), and noticed you currently have {website_status}.

            I run a small web design service where we build custom website demos for businesses before they pay anything.

            I actually put together a quick idea of how {business_name}'s site could look with a more modern design and better conversion layout.

            If you're open to it, I can build out a free, live demo tailored to your business — no upfront cost, no obligation.

            You'd be able to:

            - See a redesigned version of your site
            - Review layout, content, and structure
            - Decide if you want to keep it (only then is there a fee)

            If you're interested, just reply "demo" or fill this out here:
            {landing_page_link}

            Takes about 30 seconds.

            Either way, keep up the great work with {business_name} — I saw you've got a {rating}⭐ rating, which is awesome.

            – CJ
            MV Software"""

    return subject, body

def extract_real_email(raw_email_field):
    emails = raw_email_field.split(";")
    for e in emails:
        e = e.strip().lower()
        if e and "sentry" not in e and "wixpress" not in e:
            return e
    return ""

def main():
    logger.critical('Starting Lead Automation...')
    landing_page_link = "https://www.moultonventuresllc.com/contact"

    emails_output = []  # collect all built emails

    with open("leads_output.csv", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        for row in reader:
            business_name = row["business_name"]
            address = row["address"]
            email_addr = extract_real_email(row["email"])
            website = row["website"]
            rating = row["rating"]

            logger.critical(f"Business: {business_name}, Email: {email_addr}, Website: {website}")

            # Skip leads with no email
            if not email_addr.strip():
                logger.critical(f"  → Skipping {business_name}: no email address")
                continue

            subject, body = build_email_template(
                business_name=business_name,
                address=address,
                website=website,
                rating=rating,
                landing_page_link=landing_page_link,
            )

            emails_output.append({
                "to_email": email_addr,
                "business_name": business_name,
                "subject": subject,
                "body": body,
            })

            mark_contacted_and_remove_from_csv(email_addr)

    # Save all built emails to a CSV for easy copy-paste
    if emails_output:
        output_path = "emails_to_send.csv"
        with open(output_path, "w", newline="", encoding="utf-8") as out_file:
            writer = csv.DictWriter(out_file, fieldnames=["to_email", "business_name", "subject", "body"])
            writer.writeheader()
            writer.writerows(emails_output)
        logger.critical(f"Done. {len(emails_output)} email(s) written to {output_path}")
    else:
        logger.critical("No leads with email addresses found.")


if __name__ == "__main__":
    main()