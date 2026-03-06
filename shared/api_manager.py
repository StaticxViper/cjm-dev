from apify_client import ApifyClient
import httpx
from typing import Optional, Dict, Any
import os
from dotenv import load_dotenv
from logger import setup_logger

load_dotenv()
API_KEYS = {'Google': os.getenv("GOOGLE_API_KEY"), 'Apify': os.getenv("APIFY_API_KEY")}
APIFY_USER_ID = os.getenv("APIFY_USER_ID")

ACTORS = {'Yahoo Finance': 'architjn/yahoo-finance', 'Website Content Crawler': 'apify/website-content-crawler',
          'Instagram Post Scraper': 'apify/instagram-post-scraper'}

logger = setup_logger(
    name="api-manager",
    console_levels=["INFO", "ERROR", "CRITICAL"]  # Only these show in console, any of them can be removed.
)

class APIManager:

    def __init__(self, url=None):
        self.log = logger
        self.apify_client = ApifyClient(self.get_api_key('Apify'))

        self.default_url = 'https://httpbin.org'
        if url == None:
            url = self.default_url
            r = httpx.get(url)
            self.log.info(r.text)

    def build_request(self, base_url: str, endpoint: str, method: str = "POST",
        api: Optional[str] = None, params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        timeout: float = 10.0) -> Dict[str, Any]:
        """
        Generic API request function.

        Args:
            base_url: https://api.yourserver.com
            endpoint: /device/data
            method: HTTP method (GET, POST, etc.)
            api_key: API key for authentication
            params: Query parameters
            json_body: JSON payload
            timeout: Request timeout

        Returns:
            Parsed JSON response
        """

        headers = {
            "Content-Type": "application/json",
        }

        if api:
            api_key = self.get_api_key(api)
            headers["X-API-Key"] = api_key

        with httpx.Client(base_url=base_url, timeout=timeout) as client:
            response = client.request(
                method=method.upper(),
                url=endpoint,
                headers=headers,
                params=params,
                json=json_body,
            )

            # Raise for bad status codes
            response.raise_for_status()

        # Return JSON safely
        if response.content:
            self.log.info(response.content)
            return response.json()

        return {}

    def get_api_key(self, api:str):
        """
        Traverses through API_KEYS dict and determines which env variable to use based on given string.
        
        Args:
            api: String for grabbing API Key (Ex: 'Google' for 'GOOGLE_API_KEY')

        Returns:
            API Key String
        """
        self.log.info(f'Searching for API Key associated with: "{api}"')
        # Loop through API_KEYS
        for key,value in API_KEYS.items:
            # If API string matches key of API_KEYS, assign the value to api
            if api in key:
                self.log.info('API Key Found!')
                api = value
                break
        
        return api

    def start_apify_actor(self, actor:str = None):


        if actor is None:
            self.log.error('Apify Actor not given...')
            exit()
        else:
            actor_found = False
            for key,value in ACTORS.items():
                if actor in key:
                    actor = value
                    actor_found = True
                    break
        
        if actor_found:
            self.log.critical('Actor Found!')
        else:
            self.log.error('Actor not Found...')
            exit()

        actor_call = self.apify_client.actor(actor).call()
        results = self.get_apify_data(actor_call)
        self.log.info('Results Found via Dataset ID!')
        return results

    def get_apify_data(self, actor):
        
        return self.apify_client.dataset(actor['defaultDatasetId']).list_items().items

if __name__ == "__main__":
    instance = APIManager()
