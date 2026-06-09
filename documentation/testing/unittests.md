# Unit Tests

**Source:** `unittests/`

## Purpose

Validates core logic in automation scripts without calling live APIs. Currently covers [leadgen](../scripts/leadgen.md) scoring, Google Places parsing, CSV export, and website analysis.

## Prerequisites

- Python 3.12+
- Dependencies from `requirements/requirements.txt` installed in your virtual environment
- `scripts/lead_automation/keywords.json` and `coords.json` (loaded at import time)

Tests skip automatically if `leadgen` cannot be imported (e.g. missing deps).

## How to run

From **repo root**:

```bash
python -m unittest unittests.lead_automation.test_leadgen
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

## Related documentation

- [leadgen.md](../scripts/leadgen.md) — script under test
- [setup.md](../setup.md) — environment setup
