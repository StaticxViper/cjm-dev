# City data

`city_data_scraper.py` opens city-data.com city and crime pages in Playwright and writes a curated JSON profile (population, income, housing, education, crime index).

**Inputs:** a JSON config of cities and field groups (see the long guide). **Outputs:** one JSON profile per city in this folder's output path, as documented in the guide.

**Local run** from this directory, after `python -m playwright install chromium`:

```bash
python city_data_scraper.py --input cities.json --output-path city_profiles.json
```

**Script Manager:** `city-data`. `python -m scripts.script_manager run city-data`. The Apify copy lives in [`scripts/apify-scripts/city-data/`](../apify-scripts/city-data/). `ci.yml` tests that Actor on every pull request. No separate schedule workflow.

**Secrets:** none. Optional `MVLLC_LOGS_KEY` for log upload.

Longer guide: [documentation/scripts/city_data_scraper.md](../../documentation/scripts/city_data_scraper.md).
