import requests
import sys
from pathlib import Path


repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))

from scripts.email_manager import email_manager
from shared.logger import setup_logger

logger = setup_logger(
    name="webhook-manager",
    console_levels=["ERROR", "CRITICAL"]  # Only these show in console, any of them can be removed.
)

class WebhookManager:

    def __init__(self, url:str=None):
        
        if url is None:
            self.webhook_url = "https://hook.us2.make.com/7thupbfkql9v75p0yq1y22flimcju2nw"
        else:
            self.webhook_url = url
        logger.critical(f'URL Defined: {self.webhook_url}')

    def send_email(self, payload:dict=None):

        if payload is None: # For Testing
            payload = {
                "business_name": "Joe's Plumbing",
                "email": "cj3_31@yahoo.com",
                "subject": "TEST: Quick question about your website",
                "message": "TEST: Hey Joe, I noticed your site could use an upgrade..."
            }

        response = requests.post(self.webhook_url, json=payload)

        logger.critical(f'STATUS CODE: {response.status_code}')

# For Testing
if __name__ == "__main__":
    WebhookManager().send_email()