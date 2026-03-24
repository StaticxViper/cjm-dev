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

    perplexity_url = 'https://api.perplexity.ai'
    run_perplexity = False

    # Update stock tickers, if needed
    result = api().build_request(base_url=base_url, endpoint=ticker_endpoint, method='GET', api='Stock Analyzer')
    logger.critical(f"Current Stock Watchlist extracted: {result['tickers']}")

    # Call API Manager (Apify Functions)
    with open("previous_run_date.txt", 'r') as file:
        previous_date = file.read()
        file.close()
    todays_date = date.today().strftime("%Y-%m-%d")

    if previous_date != todays_date:
        logger.critical('New day detected. Adding Perplexity analysis and updating stock data...')
        run_perplexity = True
    else:
        logger.critical('Same day detected. Skipping Perplexity analysis, but updating stock data...')

    apify_input = {"end_date": todays_date,"start_date": previous_date,'tickers': result['tickers']}
    stock_data = api().run_apify(actor='Yahoo Finance', input=apify_input, runtime=20)
    with open("previous_run_date.txt", 'w') as file:
        file.write(todays_date)
        file.close()
    logger.critical(f'Prev Date: {previous_date}, Todays Date: {todays_date}')

    # Update dashboard with new data (Stored on dashboard database) without Perplexity analysis.
    logger.critical('Uploading stock data to dashboard...')
    api().build_request(base_url=base_url, endpoint=analyzer_endpoint, json_body=stock_data, api='Stock Analyzer')


    if run_perplexity:
        # Call Perplexity and get analysis + recent news
        # Could get earnings analysis, recent news, and overall stock sentiment
        perplexity_response_dict = {} # {ticker: {earnings_analysis: str, news_summary: str, sentiment: str}}
        for ticker in result['tickers']:
            perplexity_request = { "model": "sonar-pro",
                                "messages": [
                                    {
                                        "role": "system",
                                        "content": "You are an expert stock analyst and investor. Output strictly valid JSON only."
                                    },
                                    {
                                        "role": "user",
                                        "content": f"""Analyze the stock performance for {ticker} and provide a summary of its recent earnings, news, and overall sentiment. 
                                            Return the response in this format: {{'ticker': str, 'earnings_analysis': str, 'news_summary': str}}"""
                                    }
                                ]
                            }
            perplexity_response = api().build_request(base_url=perplexity_url, endpoint='/chat/completions', json_body=perplexity_request, api="Perplexity")
            perplexity_response_dict[ticker] = perplexity_response
        # Update dashboard with Perplexity analysis
        # NOTE: Format is ok, but would be better to have frontend accept perplexity data instead of trying to
        # place the data in the same structure as the stock data from apify.
        api().build_request(base_url=base_url, endpoint=analyzer_endpoint, json_body=perplexity_response_dict, api='Stock Analyzer')


if __name__ == "__main__":
    main()
