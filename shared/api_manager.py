import httpx
from logger import setup_logger

logger = setup_logger(
    name="api-manager",
    console_levels=["INFO", "ERROR", "CRITICAL"]  # Only these show in console, any of them can be removed.
)

class APIManager:

    def __init__(self, url=None):
        self.log = logger

        self.default_url = 'https://httpbin.org'
        if url == None:
            url = self.default_url
            r = httpx.get(url)
            self.log.info(r.text)



if __name__ == "__main__":
    instance = APIManager()
