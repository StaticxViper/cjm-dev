# Unit Tests

**Source:** `unittests/`

## Purpose

Validates core logic in automation scripts without calling live APIs. Currently covers [leadgen](../scripts/leadgen.md) scoring, Google Places parsing, JSON export, website analysis, and contact `objective` checks, plus [email discovery](../scripts/leadgen.md) extraction/confidence (mocked Google/Playwright), [leadenrich](../scripts/leadenrich.md) Facebook URL handling, name matching, and merge logic, [leadenrich_playwright](../scripts/leadenrich_playwright.md) SERP classification, SEO audit, and CRM mapping (Google/CRM patched out), [niche search](../scripts/niche_search.md) config, intent scoring, filters, and CSV export, and [property listing gen](../scripts/property_listing_gen.md) ZIP-search input validation and URL extraction (Apify patched out).

## Prerequisites

- Python 3.12+
- Dependencies from `requirements/requirements.txt` installed in your virtual environment
- `scripts/lead_automation/keywords.json` and `coords.json` (loaded at import time)

Tests skip automatically if `leadgen` cannot be imported (e.g. missing deps).

## How to run

From **repo root**:

```bash
python -m unittest unittests.lead_automation.test_leadgen
python -m unittest unittests.lead_automation.test_email_discovery
python -m unittest unittests.lead_automation.test_leadenrich
python -m unittest unittests.lead_automation.test_leadenrich_playwright
python -m unittest unittests.lead_automation.test_niche_search
python -m unittest unittests.zillow_automation.test_property_listing_gen
```

Run all tests in the package:

```bash
python -m unittest discover -s unittests -p "test_*.py"
```

Run a single test class:

```bash
python -m unittest unittests.lead_automation.test_leadgen.TestScoreLead
```

Verbose output:

```bash
python -m unittest -v unittests.lead_automation.test_leadgen
```

## Test file: `unittests/lead_automation/test_leadgen.py`

Imports `leadgen` by temporarily changing CWD to `scripts/lead_automation/` (matching how the script loads config).

### `TestScoreLead`

| Test | What it checks |
|------|----------------|
| `test_no_website_returns_ten` | No website → score 10 |
| `test_ideal_lead_zero_score` | Full signals (HTTPS, viewport, email, CTA) → score 0 |
| `test_adds_for_http_no_viewport_short_html` | Penalties stack for HTTP, no viewport, short HTML |

### `TestLeadEnrichmentSetting`

| Test | What it checks |
|------|----------------|
| `test_enabled_by_default` | `lead_enrichment` defaults to on |
| `test_legacy_settings_without_key_keep_default` | Older settings files without the key still enrich |
| `test_cli_flag_disables_and_counts_as_override` | `--no-lead-enrichment` parses and skips the interactive menu |
| `test_run_leadgen_enriches_before_output` | Enrichment runs on the qualifying rows before save/ingest |
| `test_run_leadgen_skips_enrichment_when_disabled` | Setting off means no enrichment call |
| `test_enriched_lead_already_contacted_is_dropped` | Newly found email in `contacted.txt` removes the lead |
| `test_enrich_missing_emails_*` | Returns enriched rows; an actor failure is logged, not raised |
| `test_enrich_missing_emails_playwright_*` | Playwright mode dispatches to `leadenrich_playwright`; failures are swallowed |
| `test_run_leadgen_playwright_passes_leadgen_type_to_enrichment` | Playwright discovery passes `leadgen_type="playwright"` into enrichment |
| `test_gather_leads_playwright_persists_after_each_location` | Each city is saved/uploaded before the next search starts |
| `test_persist_lead_batch_saves_and_uploads` | Location flush writes JSON and dashboard payload |
| `test_send_to_dashboard_connect_error_does_not_raise` | DNS/connect failures retry then return 0 instead of aborting the run |
| `test_persist_lead_batch_keeps_json_when_upload_fails` | City JSON is kept when dashboard ingest raises |

### `TestGetPlaces`

| Test | What it checks |
|------|----------------|
| `test_get_places_parses_results_and_stops` | Mocks Google API; verifies `place_id`, name, category parsing |

### `TestSaveResults`

| Test | What it checks |
|------|----------------|
| `test_save_results_new_file` | Writes CSV with expected headers and business name |

### `TestAnalyzeWebsite`

| Test | What it checks |
|------|----------------|
| `test_empty_url_no_request` | Empty URL skips HTTP |
| `test_parses_email_and_cta` | Extracts email and CTA from HTML |

### `TestLeadMeetsObjective`

| Test | What it checks |
|------|----------------|
| `test_phone_requires_phone` | `objective=phone` PASS/FAIL |
| `test_email_requires_email` | `objective=email` PASS/FAIL |
| `test_either_accepts_phone_or_email` | phone, email, both PASS; neither FAIL |
| `test_both_requires_phone_and_email` | only both PASS |
| `test_score_cannot_override_objective` | High score does not satisfy a missing contact |
| `test_legacy_flags_map_to_objective` / CLI tests | Old require flags normalize; `--objective` wins |

### `TestSelectionHelpers` / `TestLeadgenTypeConfig` / `TestPlaywrightDiscoveryHelpers`

| Test | What it checks |
|------|----------------|
| `test_parse_index_selection_ranges_and_none` | `1-3,5`, `all`, and `none` |
| `test_cli_leadgen_type_playwright` | `--playwright-area-expansion` persists on the config |
| `test_parse_card_fields_and_area_expansion` | Maps card phone/website/rating parse; light/dense grid sizes |
| `test_listing_needs_detail_and_high_volume_preset` | Skip detail pages when the card is complete; volume estimate |
| `test_cli_state_filter` | `--state` + `--city` narrows `coords.json` |

## Test file: `unittests/lead_automation/test_email_discovery.py`

Imports `email_discovery` the same way. Playwright and HTTP are mocked; no live Google requests.

| Test class | What it checks |
|------------|----------------|
| `TestExtractEmails` | Plain text, mailto, duplicates, malformed text, false positives, JSON-LD |
| `TestQueriesAndConfidence` | Location-aware queries; HIGH domain match; LOW/MEDIUM Gmail rules |
| `TestGoogleParsingAndBlocks` | SERP HTML parse, CAPTCHA detection, official-site pick |
| `TestEnrichmentFlow` | Skip when email exists, cache hit, CAPTCHA does not raise, accept/reject rules, Google search works inside an asyncio loop |

## Test file: `unittests/lead_automation/test_leadenrich.py`

Imports `leadenrich` the same way (CWD switched to `scripts/lead_automation/`). Apify actors are patched out, so no run costs credits.

| Test class | What it checks |
|------------|----------------|
| `TestNormalizeFacebookUrl` | Canonicalizes vanity, `/pg/`, legacy `/pages/`, and `profile.php?id=` URLs; rejects groups, events, and non-Facebook hosts |
| `TestNameMatching` | Name normalization (apostrophes, legal suffixes) and that only sufficiently similar pages are matched |
| `TestLocationHint` | `City, Country` hint parsed from a Google formatted address |
| `TestEmailExtraction` | Email pulled from page fields; image filenames and junk domains filtered |
| `TestCandidateSelection` | Which leads are picked up, skipped, or retried across runs |
| `TestApplyEnrichment` | Status and fields written for each outcome |
| `TestResolvePageUrls` | Facebook websites skip the search actor; weak matches stay unresolved |
| `TestScrapeFacebookPages` | Batching, URL-variant indexing, and actor failure handling |
| `TestRunEnrichment` | End-to-end merge, `--limit`, `--dry-run`, dashboard payload, missing API key |
| `TestEnrichLeads` | In-memory entry point used by leadgen: mutates rows in place, returns changed rows, no-ops without candidates or an API key |
| `TestSaveLeads` | Atomic write leaves no temp file; malformed input rejected |

## Test file: `unittests/lead_automation/test_leadenrich_playwright.py`

Imports `leadenrich_playwright` the same way (CWD switched to `scripts/lead_automation/`). Google searches, site visits, and CRM export are patched out.

| Test class | What it checks |
|------------|----------------|
| `TestSerpClassification` | Facebook vs official website vs directory; name-similarity gate |
| `TestResearchQueries` | Location-aware Google queries include facebook/website variants |
| `TestSeoAudit` | Healthy HTML scores low; thin HTTP pages collect issues; load errors score 100 |
| `TestCrmMapping` | CRM export body, field mapping, pagination, `--limit` |
| `TestCandidateSelection` | Facebook-enriched leads still get Playwright research; completed research is skipped |
| `TestApplyResearch` | `enriched` / `researched` / `no_match` / `scrape_failed` |
| `TestEnrichLeads` | In-memory entry point mutates rows with mocked search/visit; dry-run does not write |
| `TestRunEnrichment` | `--from-crm` key check, CRM save, dashboard receives newly emailed leads |
| `TestCliConfig` | `--from-crm` flags map onto `EnrichConfig` |

## Test file: `unittests/lead_automation/test_niche_search.py`

Imports niche search modules the same way (CWD switched to `scripts/lead_automation/`). Google, website fetches, and email discovery are patched or fed HTML fixtures.

| Test class | What it checks |
|------------|----------------|
| `TestNicheConfig` | Loads 20 niches, unique/stable query generation, display-name lookup, negative keywords |
| `TestDedupAndFranchise` | Cross-query `place_id` dedupe; Petco/PetSmart franchise detection |
| `TestWebsiteAndSocial` | Social URL ≠ website; broken site only after a failed request; quality bands; malformed `http://[` hrefs are skipped; URL-only social is not active |
| `TestIntentScoring` | Deterministic additive scores, negatives, breakdown, evidence-based outreach angle, seven fixtures |
| `TestFiltersExportAndIngest` | Result presets, CSV columns, `high-pri-lead` dashboard tags, keyword ingest unchanged, search job filters franchises, per-city save/upload + running lead stats |

## Test file: `unittests/zillow_automation/test_property_listing_gen.py`

Imports `property_listing_gen` the same way (CWD switched to `scripts/zillow_automation/`). Apify is patched out, so no run costs credits.

| Test class | What it checks |
|------------|----------------|
| `TestExtractPropertyUrls` | Reads `propertyUrl` / `detailUrl`, skips missing or non-Zillow hosts, dedupes, unwraps `{items: [...]}` |
| `TestNormalizeSearchInput` | Example actor input accepted; ZIP codes coerced to strings; empty/missing `zipCodes` rejected |
| `TestLoadAndSave` | Settings JSON loads; URL list writes as a JSON array with no leftover temp file |
| `TestResolveSearchInput` | CLI flags overlay file values without changing unspecified fields |
| `TestGenerateListings` | Actor called as `Zillow ZIP Search`; URLs written; missing `APIFY_API_KEY` skips the run |

## Related documentation

- [leadgen.md](../scripts/leadgen.md) — script under test
- [niche_search.md](../scripts/niche_search.md) — script under test
- [leadenrich.md](../scripts/leadenrich.md) — script under test
- [leadenrich_playwright.md](../scripts/leadenrich_playwright.md) — script under test
- [property_listing_gen.md](../scripts/property_listing_gen.md) — script under test
- [setup.md](../setup.md) — environment setup
