import sys
from pathlib import Path

# Add repo root to sys.path
repo_root = Path(__file__).resolve().parents[2]  # stock_analyzer.py -> stock_analyzer/ -> scripts/ -> repo_root
sys.path.insert(0, str(repo_root))

from datetime import date
from shared.api_manager import APIManager as api
from shared.logger import setup_logger

logger = setup_logger(
    name="stock-analyzer",
    console_levels=["ERROR", "CRITICAL"]  # Only these show in console, any of them can be removed.
)


def main():
    logger.critical('Starting Stock Analysis...')
    base_url = 'https://bvkgatxfefnsfstwihxu.supabase.co/functions/v1'#/moulton-api'
    analyzer_endpoint = '/stock-data/ingest'
    ticker_endpoint = '/stock-data/tickers'


    # Update stock tickers, if needed
    result = api().build_request(base_url=base_url, endpoint=ticker_endpoint, method='GET')
    logger.critical(f"Current Stock Watchlist extracted: {result['tickers']}")

    # Call API Manager (Apify Functions)
    with open("previous_run_date.txt", 'r') as file:
        previous_date = file.read()
        file.close()
    todays_date = date.today().strftime("%Y-%m-%d")
    apify_input = {"end_date": todays_date,"start_date": previous_date,'tickers': result['tickers']}
    stock_data = api().run_apify(actor='Yahoo Finance', input=apify_input, runtime=20)
    with open("previous_run_date.txt", 'w') as file:
        file.write(todays_date)
        file.close()
    logger.critical(f'Prev Date: {previous_date}, Todays Date: {todays_date}')

    # Temp log (Until dashboard enpoint is made)
    #logger.info(stock_data)

    # Update dashboard with new data (Stored on dashboard database)
    api().build_request(base_url=base_url, endpoint=analyzer_endpoint, json_body=stock_data)



if __name__ == "__main__":
    main()
