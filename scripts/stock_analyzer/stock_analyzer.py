import sys
from pathlib import Path

# Add repo root to sys.path
#sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
repo_root = Path(__file__).resolve().parents[2]  # stock_analyzer.py -> stock_analyzer/ -> scripts/ -> repo_root
sys.path.insert(0, str(repo_root))

from shared.api_manager import APIManager as api
import json
from shared.logger import setup_logger

logger = setup_logger(
    name="stock-analyzer",
    console_levels=["ERROR", "CRITICAL"]  # Only these show in console, any of them can be removed.
)


def main():
    logger.critical('Starting Stock Analysis...')

    # Get stock tickers
    with open("scripts/stock_analyzer/stock_tickers.json", "r") as file:
        content = file.read()
        json_content = json.loads(content)
        tickers = json_content['tickers'] # List of stock tickers
        file.close()


    # Call API Manager (Apify Functions)
    stock_data = api().run_apify(actor='Yahoo Finance', input=json_content, runtime=20)

    # Temp log (Until dashboard enpoint is made)
    logger.info(stock_data)

    # Update dashboard with new data (Stored on dashboard database)




if __name__ == "__main__":
    main()
