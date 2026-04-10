import csv
import email
import sys
from pathlib import Path
import pandas as pd

# Add repo root to sys.path
repo_root = Path(__file__).resolve().parents[2]  # stock_analyzer.py -> stock_analyzer/ -> scripts/ -> repo_root
sys.path.insert(0, str(repo_root))

from scripts.email_manager import email_manager
from shared.logger import setup_logger

logger = setup_logger(
    name="lead-automation",
    console_levels=["ERROR", "CRITICAL"]  # Only these show in console, any of them can be removed.
)



def mark_contacted_and_remove_from_csv(email, csv_path="leads_output.csv"):
    email = (email or "").strip().lower()
    if not email:
        return

    # -----------------------------
    # 1. Append to contacted.txt
    # -----------------------------
    with open("contacted.txt", "a", encoding="utf-8") as f:
        f.write(email + "\n")

    # -----------------------------
    # 2. Remove from CSV safely
    # -----------------------------
    try:
        df = pd.read_csv(csv_path)
    except Exception:
        return

    if df.empty or "email" not in df.columns:
        return

    # normalize emails in CSV
    df["email"] = df["email"].fillna("").astype(str).str.lower()

    # remove contacted lead
    df = df[df["email"] != email]

    # save back safely
    df.to_csv(csv_path, index=False)

def main():
    logger.critical('Starting Lead Automation...')


    # Parse leads_output.csv for lead info
    with open("leads_output.csv", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        for row in reader:
            business_name = row["business_name"]
            address = row["address"]
            phone_google = row["phone_google"]
            phone_website = row["phone_website"]
            email = row["email"]
            website = row["website"]
            rating = row["rating"]
            user_ratings_total = row["user_ratings_total"]
            lead_score = row["lead_score"]

            print(business_name, email, website)
    


    '''
    # Build email message
    msg = email_manager.build_email(
        sender="you@gmail.com",
        recipients=["target@email.com"],
        subject="Test Email",
        body_text="Hello from Python!",
        body_html="<h1>Hello</h1><p>This is HTML</p>",
        attachments=["file.txt"],  # optional
    )

    # Send email message
    email_manager.send_email(
        smtp_server="smtp.gmail.com",
        port=587,
        sender="you@gmail.com",
        password="your_app_password",
        recipients=["target@email.com"],
        message=msg,
    )'''

    mark_contacted_and_remove_from_csv(email)

if __name__ == "__main__":
    main()
