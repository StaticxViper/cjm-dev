import csv
import sys
from pathlib import Path

# Add repo root to sys.path
repo_root = Path(__file__).resolve().parents[2]  # stock_analyzer.py -> stock_analyzer/ -> scripts/ -> repo_root
sys.path.insert(0, str(repo_root))

from scripts.email_manager import email_manager
from shared.logger import setup_logger

logger = setup_logger(
    name="lead-automation",
    console_levels=["ERROR", "CRITICAL"]  # Only these show in console, any of them can be removed.
)


def main():
    logger.critical('Starting Lead Automation...')


    # Parse leads_output.csv for lead info
    with open("leads.csv", newline="", encoding="utf-8") as file:
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

    with open("contacted.txt", "a", encoding="utf-8") as f:
        f.write(email + "\n")


if __name__ == "__main__":
    main()
