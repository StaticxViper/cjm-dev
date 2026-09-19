# Niche Lead Search

**Source:** `scripts/lead_automation/niche_search.py`

## Purpose

Find high-intent, owner-operated website prospects in a chosen micro-niche. This is a separate path from the existing keyword run in [leadgen](leadgen.md). It reuses Places/Playwright discovery, `leadfilter` identities, franchise lists, and dashboard ingest. It does **not** call `process_businesses()` or the legacy `score_lead()` model.

`high-pri-lead` is added only when the chosen niche has `high_pri_lead: true` in `niches.json` (the 20 micro-niches listed there). Other niche presets and the existing keyword search do not get that tag.

## How to run

```bash
cd scripts/lead_automation

# Interactive menu option 5
python leadgen.py

# Non-interactive niche job
python leadgen.py --niche "specialty_dog_trainers" --state NJ,PA,NY --min-reviews 20 --min-rating 4.5 --min-score 55 --exclude-strong-websites

# Review saved results
python leadgen.py --review-leads --json-path niche_leads_output.json
```

Default output: `niche_leads_output.json` (kept separate from `leads_output.json` so intent scores are not mixed with legacy `lead_score` values).

## Configuration

| File | Description |
|------|-------------|
| `niches.json` | 20 micro-niche presets: queries, negatives, high-value terms, signal detectors, suggested floors |
| `intent_score_rules.json` | Additive intent weights, enrichment stage gates, result presets |
| `franchises.json` | Shared chain blocklist (reused by both search paths) |

`niche_config.py` loads and validates those files. Niche-specific scoring overlays live under each niche's `scoring_adjustments`.

## Pipeline

1. Generate multiple queries from the niche (search + related + extras).
2. Discover via Google Places or Playwright Maps (same `leadgen_type` as saved settings).
3. Deduplicate across queries.
4. Stage 1: Places/Maps fields only.
5. Stage 2: cheap website existence/status check.
6. Stage 3: deep website analysis only for leads that pass cheap criteria.
7. Detect signals and compute additive `lead_score` + breakdown (`score_model: intent_v1`).
8. Stage 4: social classification for promising leads. Active social requires a retrieved post date.
9. Stage 5: email enrichment only at/above the configured score threshold (default 55).
10. Rank, apply user filters, save, optional dashboard ingest, then the CLI reviewer.

Progress is printed as Google results, unique businesses, websites analyzed, social profiles found, high-intent count, and score 55+.

## Scoring

Intent scoring is additive and configurable. Higher is a better website prospect. A website is not automatically a penalty; quality bands and conversion evidence decide bonuses and deductions. Unproven claims (broken site, active social, Google Ads, owner-operated) add 0 points.

The CLI reviewer prints the score breakdown and detected signals.

## Results reviewer

After a search (or `--review-leads`):

- Sort by score, reviews, rating, website quality, social activity, or date
- Filter or apply presets: Highest Intent, No Website, Broken Website, Social-First, High Value, Easy Outreach
- View a full lead profile
- Export the filtered set to CSV
