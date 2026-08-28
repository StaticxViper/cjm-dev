from apify_client import ApifyClient
import apify_client
import httpx
import json
from typing import Optional, Dict, Any
import os
from dotenv import load_dotenv
from helper_scripts.utils.logger.logger import setup_logger

load_dotenv()
API_KEYS = {'Google': os.getenv("GOOGLE_API_KEY"), 'Apify': os.getenv("APIFY_API_KEY"), 'Stock Analyzer': os.getenv("STOCK_INGEST_TOKEN"),
            'ChatGPT': os.getenv("CHATGPT_API_KEY"), 'Perplexity': os.getenv("PERPLEXITY_API_KEY"), 'Chikara Realms': os.getenv("CHIKARA_REALMS_SECRET"),
            'Lead Ingest': os.getenv("LEAD_INGEST_KEY"), 'MVLLC Logs': os.getenv("MVLLC_LOGS_KEY")}
APIFY_USER_ID = os.getenv("APIFY_USER_ID")

ACTORS = {'Yahoo Finance': 'architjn/yahoo-finance', 'Website Content Crawler': 'apify/website-content-crawler',
          'Instagram Post Scraper': 'apify/instagram-post-scraper',
          'LinkedIn Company Employees': 'harvestapi/linkedin-company-employees'}

logger = setup_logger(
    name="api-manager",
    console_levels=["INFO", "ERROR", "CRITICAL"]  # Only these show in console, any of them can be removed.
)


def _extract_dataset_id(actor_run) -> str:
    """Read the default dataset ID off an Apify actor run.

    apify-client < 3 returns a plain dict keyed by 'defaultDatasetId'; >= 3 returns a
    typed Run model whose fields are snake_case and not subscriptable. dict(run) from
    a v3 model also uses snake_case keys, so both spellings are checked.
    """
    if actor_run is None:
        raise RuntimeError('Apify actor run returned nothing (the run likely failed or timed out).')

    if isinstance(actor_run, dict):
        dataset_id = actor_run.get('defaultDatasetId') or actor_run.get('default_dataset_id')
        if dataset_id:
            return dataset_id
        raise RuntimeError(f'No default dataset ID in Apify run dict (keys: {list(actor_run.keys())}).')

    for attribute in ('default_dataset_id', 'defaultDatasetId'):
        dataset_id = getattr(actor_run, attribute, None)
        if dataset_id:
            return dataset_id

    dump = getattr(actor_run, 'model_dump', None)
    if callable(dump):
        dumped = dump()
        if isinstance(dumped, dict):
            dataset_id = dumped.get('default_dataset_id') or dumped.get('defaultDatasetId')
            if dataset_id:
                return dataset_id

    raise RuntimeError(f'No default dataset ID on Apify run object of type {type(actor_run).__name__}.')


class APIManager:

    def __init__(self, url:str = None, test:bool = False):
        if test:
            logger.critical('TEST MODE: ENABLED')
            test_url = 'https://httpbin.org'
            url = test_url
            r = httpx.get(url)
            logger.info(r)
            #logger.info(r.text)
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
            bearer_token_apis = ["Stock Analyzer", "Perplexity", "MVLLC Logs"]
            api_key = self.get_api_key(api)
            if api in bearer_token_apis:
                headers["Authorization"] = f"Bearer {api_key}"
            else:
                headers["X-API-Key"] = api_key

        with httpx.Client(base_url=base_url, timeout=timeout) as client:
            response = client.request(
                method=method.upper(),
                url=endpoint,
                headers=headers,
                params=params,
                json=json_body,
            )
            logger.info("STATUS: %s", response.status_code)
            logger.info("RESPONSE: %s", response.text)

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
        logger.info(f'Searching for API Key associated with: "{api}"')
        # Loop through API_KEYS
        for key,value in API_KEYS.items():
            # If API string matches key of API_KEYS, assign the value to api
            try:
                if api in key:
                    logger.info('API Key Found!')
                    api = value
                    break
            except Exception:
                logger.error('Could not find API Key!')
        
        return api

    def run_apify(self, actor:str = None, input = None, runtime:int = 60):
        """ Run a specified actor via Apify API, and then extract the acquired data via Dataset ID. 
        
        Args:
            actor: Apify actor to be executed

        Returns:
            Acquired JSON Data
        """
        del runtime

        if actor is None:
            raise ValueError('Apify actor not given.')

        actor_id = None
        for key, value in ACTORS.items():
            if actor in key:
                actor_id = value
                break

        if not actor_id:
            raise ValueError(f'Apify actor not found: {actor}')

        logger.critical('Actor Found!')
        logger.info('apify-client version: %s', getattr(apify_client, '__version__', 'unknown'))

        actor_call = self.apify_client.actor(actor_id).call(run_input=input)
        dataset_id = _extract_dataset_id(actor_call)
        logger.info('Apify dataset ID: %s', dataset_id)
        result = self.get_apify_data(dataset_id=dataset_id)
        logger.info('Results Found via Dataset ID!')
        return result

    def get_apify_data(self, actor_call = None, dataset_id = None):
        """ Extract the acquired data via Dataset ID. 
        
        Args:
            actor_call: Actor run object (dict or apify-client v3 Run model)
            dataset_id: ID for acquiring existing data, without running an actor.

        Returns:
            Acquired JSON Data
        """
        if dataset_id is None:
            dataset_id = _extract_dataset_id(actor_call)
        page = self.apify_client.dataset(str(dataset_id)).list_items()
        return getattr(page, 'items', page)

if __name__ == "__main__":
    instance = APIManager(test=True)
