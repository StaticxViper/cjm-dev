import json
import time
from datetime import date
from pathlib import Path
from helper_scripts.api_manager.api_manager import APIManager as api
from helper_scripts.utils.logger.logger import setup_logger

PREVIOUS_RUN_DATE_FILE = Path(__file__).resolve().parent / "previous_run_date.txt"


def _parse_perplexity_analysis(perplexity_response: dict, ticker: str) -> dict:
    """Extract the structured analysis JSON from a Perplexity chat completion response."""
    content = perplexity_response["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:]).strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        logger.error("Failed to parse Perplexity JSON for %s", ticker)
        return {"ticker": ticker, "earnings_analysis": "", "news_summary": ""}


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
    logger.critical(f"Last run date: {result['last_run_date']}")

    # Call API Manager (Apify Functions)
    previous_date = str(result['last_run_date']) #PREVIOUS_RUN_DATE_FILE.read_text(encoding="utf-8").strip()
    todays_date = date.today().strftime("%Y-%m-%d")

    if previous_date != todays_date:
        logger.critical('New day detected. Adding Perplexity analysis and updating stock data...')
        run_perplexity = True
    else:
        logger.critical('Same day detected. Skipping Perplexity analysis, but updating stock data...')

    # #region agent log
    with open("debug-16fad7.log", "a", encoding="utf-8") as _df:
        _df.write(json.dumps({"sessionId": "16fad7", "hypothesisId": "C", "location": "stock_analyzer.py:main:date_check", "message": "date check", "data": {"previous_date": previous_date, "todays_date": todays_date, "run_perplexity": run_perplexity, "date_file": str(PREVIOUS_RUN_DATE_FILE)}, "timestamp": int(time.time() * 1000)}) + "\n")
    # #endregion

    apify_input = {"end_date": todays_date,"start_date": previous_date,'tickers': result['tickers']}
    stock_data = api().run_apify(actor='Yahoo Finance', input=apify_input)
    PREVIOUS_RUN_DATE_FILE.write_text(todays_date, encoding="utf-8")
    logger.critical(f'Prev Date: {previous_date}, Todays Date: {todays_date}')

    # Update dashboard with new data (Stored on dashboard database) without Perplexity analysis.
    logger.critical('Uploading stock data to dashboard...')
    api().build_request(base_url=base_url, endpoint=analyzer_endpoint, json_body=stock_data, api='Stock Analyzer')


    if run_perplexity:
        # Call Perplexity and get analysis + recent news
        # Could get earnings analysis, recent news, and overall stock sentiment
        perplexity_analysis = []
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
            perplexity_response = api().build_request(
                base_url=perplexity_url,
                endpoint='/chat/completions',
                json_body=perplexity_request,
                api="Perplexity",
                timeout=120.0,
            )
            perplexity_analysis.append(_parse_perplexity_analysis(perplexity_response, ticker))
        # Ingest endpoint accepts an array (Apify price rows) or {"stocks": [...]} for analysis rows.
        perplexity_payload = {"stocks": perplexity_analysis}
        # #region agent log
        with open("debug-16fad7.log", "a", encoding="utf-8") as _df:
            _df.write(json.dumps({"sessionId": "16fad7", "hypothesisId": "D", "location": "stock_analyzer.py:main:perplexity_ingest", "message": "perplexity ingest payload", "data": {"record_count": len(perplexity_analysis), "payload_keys": list(perplexity_payload.keys()), "sample_ticker": perplexity_analysis[0].get("ticker") if perplexity_analysis else None}, "timestamp": int(time.time() * 1000)}) + "\n")
        # #endregion
        logger.critical('Uploading Perplexity analysis to dashboard...')
        api().build_request(base_url=base_url, endpoint=analyzer_endpoint, json_body=perplexity_payload, api='Stock Analyzer')
        logger.critical('Stock analysis complete.')


if __name__ == "__main__":
    main()
