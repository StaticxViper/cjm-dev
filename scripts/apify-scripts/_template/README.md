# Actor template

Copy `scripts/apify-scripts/_template/` to `scripts/apify-scripts/<name>/` and replace the scraper body. Do not publish this folder. Amazon, YouTube, and Instagram wait until city-data and Google Business have been accepted.

This packaging is issue #128. The city-data CLI is issue #99. Google match rules are issue #127.

## Contract

Every Actor is a copy of this folder:

- `.actor/actor.json` sets `dockerContextDir` to the repo root (`../../../..` from `.actor/`) and points at the Actor `Dockerfile`.
- `.actor/input_schema.json` keeps `headless` (default true). Add a proxy field when the target needs one.
- `.actor/dataset_schema.json` documents dataset columns, including nested objects, with an Overview and a Detail view.
- `.actor/actor.json` sets `defaultRunOptions.timeoutSecs`. A published Actor adds `.actor/pay_per_event.json` and charges `result` only for a successful row.
- `src/__main__.py` runs `asyncio.run(main())`. `src/main.py` uses `async with Actor` and runs sync Playwright inside `asyncio.to_thread`.
- `src/runtime.py` re-exports `scripts/apify-scripts/runtime.py` (repo imports, robots fetches with jittered retry on HTTP 429 / 5xx, timestamps, and the pay-per-event push). Business logic stays in the local CLIs and is imported, not moved.
- `Dockerfile` uses `apify/actor-python-playwright:3.12`, user `myuser`, workdir `/home/myuser`, and `COPY --chown=myuser:myuser`. Do not pip-install a different Playwright build. Set `CJM_REPO_ROOT` when the image must import repo modules.
- `requirements.txt` stays lean. `fixtures/INPUT.json` is the committed sample. Local `apify run` storage is gitignored.
- `README.md` is the marketplace draft: what it does, input, output sample, limitations, robots / ToS, pricing placeholder.

Shared behavior:

- Default headless, including on the platform. The base image already provides a virtual display if a run is headed.
- Delays stay in the source session. Do not tighten them in the Actor.
- A block page pushes one `blocked` or `error` row, writes key-value `SUMMARY`, and the run exits 0. Proxy rotation and CAPTCHA solving may be used when a target requires them. Spend caps can land in a follow-up.
- One dataset item per input city or query, via `Actor.push_data`.
- `APIFY_TOKEN` publishes. `APIFY_API_KEY` is the existing consumer key. Neither is hardcoded.

## Listing draft (replace after you copy)

### What it does

One paragraph. Name the site, the fields, and that the Actor is low-volume research.

### Input

Show a sample JSON object.

### Output

Show one dataset item.

### Limitations

Rate limits, pages that are skipped, and what the Actor refuses to do.

### Robots and terms

Say which paths are requested, that robots.txt is checked with the longest-match evaluator, and any site terms that restrict automated extraction.

### Pricing

Placeholder only. Compute units or pay-per-result. Not a live price.

### Categories

Suggest Console categories. Do not invent an `actor.json` categories field.

## Local run

From the copied Actor directory, with the repo virtualenv active:

```bash
mkdir -p storage/key_value_stores/default
cp fixtures/INPUT.json storage/key_value_stores/default/INPUT.json
apify run --purge
```

Platform publish (`apify push`, public vs private) waits for an explicit go-ahead. See `scripts/apify-scripts/README.md`.
