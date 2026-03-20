from apify_client import ApifyClient
import httpx
import json
from typing import Optional, Dict, Any
import os
from dotenv import load_dotenv
from .logger import setup_logger

load_dotenv()
API_KEYS = {'Google': os.getenv("GOOGLE_API_KEY"), 'Apify': os.getenv("APIFY_API_KEY"), 'Stock Analyzer': os.getenv("STOCK_INGEST_TOKEN"),
            'ChatGPT': os.getenv("CHATGPT_API_KEY"), 'Perplexity': os.getenv("PERPLEXITY_API_KEY")}
APIFY_USER_ID = os.getenv("APIFY_USER_ID")

ACTORS = {'Yahoo Finance': 'architjn/yahoo-finance', 'Website Content Crawler': 'apify/website-content-crawler',
          'Instagram Post Scraper': 'apify/instagram-post-scraper'}

logger = setup_logger(
    name="api-manager",
    console_levels=["INFO", "ERROR", "CRITICAL"]  # Only these show in console, any of them can be removed.
)

class APIManager:

    def __init__(self, url:str = None, test:bool = False):
        self.log = logger
        if test:
            self.log.critical('TEST MODE: ENABLED')
            test_url = 'https://httpbin.org'
            url = test_url
            r = httpx.get(url)
            self.log.info(r)
            #self.log.info(r.text)
        else:
            self.apify_client = ApifyClient(self.get_api_key('Apify'))
            self.base_url = url

    def build_request(
        self,
        base_url: str,
        endpoint: str,
        method: str = "POST",
        api: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        timeout: float = 10.0
    ) -> Dict[str, Any]:
        """
        Generic API request function that always returns parsed JSON (Python dict/list)
        even if the response headers are wrong.
        """

        headers = {"Content-Type": "application/json"}

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

            # Raise for bad HTTP status
            response.raise_for_status()

        # Force parse JSON manually to ensure we return dict/list
        if response.content:
            try:
                return json.loads(response.content.decode("utf-8"))
            except json.JSONDecodeError:
                # If parsing fails, return raw string as fallback
                return {"raw": response.text}

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
        for key,value in API_KEYS.items():
            # If API string matches key of API_KEYS, assign the value to api
            try:
                if api in key:
                    self.log.info('API Key Found!')
                    api = value
                    break
            except Exception:
                self.log.error('Could not find API Key!')
        
        return api

    def run_apify(self, actor:str = None, input = None, runtime:int = 60):
        """ Run a specified actor via Apify API, and then extract the acquired data via Dataset ID. 
        
        Args:
            actor: Apify actor to be executed

        Returns:
            Acquired JSON Data
        """

        try:
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

            # Run Actor
            actor_call = self.apify_client.actor(actor).call(run_input=input)
            # Get data via Dataset ID
            result = self.get_apify_data(actor_call=actor_call)
            self.log.info('Results Found via Dataset ID!')
        except RuntimeError as e:
            self.log.error(f'Actor run error: {e}')
        except Exception as e:
            self.log.error(f'Unexpected error communicating with Apify: {e}')

        return result

    def get_apify_data(self, actor_call = None, dataset_id = None):
        """ Extract the acquired data via Dataset ID. 
        
        Args:
            actor_call: Actor Client obj reference
            dataset_id: ID for acquirring existing data, without running an actor.

        Returns:
            Acquired JSON Data
        """

        try:
            if actor_call is not None:
                result = self.apify_client.dataset(actor_call['defaultDatasetId']).list_items().items
            else:
                result = self.apify_client.dataset(str(dataset_id)).list_items().items
        except ValueError as e:
            self.log.error(f'Dataset error: {e}')
        except Exception as e:
            self.log.error(f'Unexpected error communicating with Apify: {e}')

        return result

if __name__ == "__main__":
    instance = APIManager(test=True)
