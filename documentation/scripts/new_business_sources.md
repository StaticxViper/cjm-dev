# New-business sources

**Config:** `scripts/lead_automation/new_business_sources.json`  
**Code:** `scripts/lead_automation/new_business_sources/`  
**Run from:** [leadgen.md](leadgen.md) (`--mode new-business` or menu option 6)

Checked 2026-10-05. A source runs only when `enabled` is true and `status` is `verified`. Everything else is recorded and skipped. No source is fetched through a login, a paywall, a CAPTCHA, or a `robots.txt` disallow. Paid reports are not purchased. The Florida SFTP password is not stored.

## Verification

| Id | Status | Enabled | What was checked |
|----|--------|---------|------------------|
| `ny_active_corporations` | verified | yes | SODA `https://data.ny.gov/resource/n9v6-gdp6.json` (`n9v6-gdp6`). `initial_dos_filing_date` filters. robots.txt allows `/resource/` (crawl-delay 1). Active entities only, monthly, not a legal certificate. `location_*` is often null, so many rows stay `geo_unverified`. |
| `pa_registered_businesses` | verified | yes | SODA `https://data.pa.gov/resource/xvd7-5r2c.json` (`xvd7-5r2c`). `creationdate`, city, county, address. robots.txt allows `/resource/`. The distinct view `3urc-uaba` has no `creationdate`, so it is not used. |
| `co_business_entities` | verified | yes | SODA `https://data.colorado.gov/resource/4ykn-tg5h.json` (`4ykn-tg5h`). `entityformdate`, principal address, Good Standing only. Agent first and last name are stored as a public registered-agent contact. The agent mailing address is not copied. |
| `phl_business_licenses` | verified | yes | Philadelphia Carto `business_licenses`. `initialissuedate` is a license date, not a formation date. Rental and Vacant Residential rows are excluded. Food, vehicle, vendor, tow, sidewalk cafe, tire, and child-care licenses in Active status are kept. robots.txt disallows `/api/` only for named bots. |
| `google_maps` | verified | yes | `www.google.com/robots.txt` allows `/maps/search/` and `/maps/place/`. Used to fill website, phone, category, status, and place URL. `fetch()` returns no discovery rows. A low review count is not newness evidence. |
| `google_search` | blocked | no | `robots.txt` `Disallow: /search`. The adapter parses a saved fixture in `--dry-run` and does not request `/search`. |
| `nj_dores` | blocked | no | NJ Business Records Service is a name lookup. Standing certificates and document copies are paid. No free formation-date range was found. Not queried. |
| `nj_open_data` | candidate | no | `data.nj.gov` catalog searches for corporation / revenue enterprise did not return a formation dataset (one hit was a NJ Transit annual report). |
| `nj_county_clerks` | candidate | no | No verified free date-range trade-name index for the counties behind coords.json cities. Cherry Hill is Camden County and Cinnaminson is Burlington County; those counties are not hard-coded. Name-search and account-gated indexes are skipped. |
| `cherry_hill_licenses` | candidate | no | `https://www.chnj.gov/379/Licensing` publishes application PDFs, not an issued-license roster. |
| `cinnaminson_directory` | candidate | no | `https://cinnaminsonnj.org/business-directory/` has name, industry, address, phone, and website, and no added or opening date. |
| `local_chambers` | candidate | no | Southern NJ Chamber directory is a category list. No dated new-member or ribbon-cutting page was verified. |
| `de_division_of_corporations` | blocked | no | Delaware ICIS says automated tools and data mining are prohibited. Extra records cost a fee. Not fetched. |
| `fl_sunbiz_daily` | candidate | no | Daily files are free but the download is an SFTP login. Credentials are not stored. Not fetched. |
| `tx_business_entities` | candidate | no | `data.texas.gov` catalog request failed TLS verification. No dataset was confirmed. |
| `example_public_table` | candidate | no | Synthetic HTML fixture for the generic table adapter. Not a live source. |

## Politeness

- One request in flight per host. Sources run in sequence.
- Random delay from each entry's `rate_limit` (default 3–7 seconds, same range as email discovery).
- `robots.txt` is read before an HTTP or Playwright fetch. A disallow sets status `robots_disallowed` and skips the source.
- CAPTCHA, block, and login pages stop that source for the rest of the run. Nothing is solved, retried around the block, or sent through a proxy.
- Network errors, HTTP 429, and 5xx retry up to twice, honoring `Retry-After`.
- Failures are isolated. Partial results are saved. Artifacts go to `new_business_artifacts/<run_ts>/<source_id>/` unless `--no-artifacts` is set.

## Add a source

Generic sources need only a `new_business_sources.json` entry:

- `adapter`: `http_table` (public HTML table; `table.columns` maps fields to header names) or `open_data` (`query.style` `socrata` or `carto`).
- `newness_field` and `newness_type` (`registration_date`, `formation_date`, `filing_date`, `license_date`, or `opening_date`).
- `coverage.states` / `counties` / `cities`.
- `access`, `terms_checked` (`date` and `note`), `status`, `enabled`, `rate_limit`, `notes`.

Leave `enabled` false and `status` `candidate` until a live check confirms the endpoint is public, free, and allowed by robots.txt, and that it carries a date. Then set `status` to `verified` and `enabled` to true.

A source that does not fit those adapters gets `scripts/lead_automation/new_business_sources/custom/<module>.py` with a class `Adapter(entry)` and `"adapter": "custom.<module>"` in the JSON entry.

`--list-sources` prints id, category, coverage, status, enabled, and the last `check_access()` result. An unknown `--sources` id exits with the valid id list.

## Regions

`geo_regions.json` ships with `"regions": {}`. Add a name only if you want `--region` to select it:

```json
{
  "regions": {
    "example": {
      "state": "NJ",
      "counties": [],
      "cities": ["Cherry Hill", "Cinnaminson"],
      "zips": []
    }
  }
}
```

Empty `cities` selects the whole `state`. Nothing in this file is filled in for you.

## Cherry Hill coordinates

`coords.json` has Cherry Hill at `39.9526,-75.1652` and Philadelphia at `39.952584,-75.165222`. Coordinate searches for Cherry Hill are centered on Philadelphia. Text queries that name the city are unaffected. The file was not changed.
