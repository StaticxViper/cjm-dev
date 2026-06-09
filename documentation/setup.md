# Setting Up cjm-dev

Step-by-step guide for configuring a fresh clone of this repository on a new machine.

## 1. Clone the repository

```bash
git clone <repository-url>
cd cjm-dev
```

## 2. Install Python 3.12+

Python 3.12 is used in CI (see `.github/workflows/stock_analyzer-Automation.yml`). Install Python 3.12 or newer from [python.org](https://www.python.org/downloads/) or your system package manager.

Verify:

```bash
python --version
```

## 3. Create a virtual environment

```bash
python -m venv .venv
```

**Windows (PowerShell):**

```powershell
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux:**

```bash
source .venv/bin/activate
```

## 4. Install dependencies

```bash
pip install -r requirements/requirements.txt
```

Packages include: `requests`, `pandas`, `beautifulsoup4`, `python-dotenv`, `httpx`, `apify-client`, `openai`, `perplexityai`.

## 5. Create a `.env` file at the repo root

The repo gitignores `*.env`. Create `cjm-dev/.env` and add only the keys you need for the scripts you plan to run. See [README.md](README.md#environment-variables) for the full variable list.

Example structure (replace values with your own keys):

```env
# AI
PERPLEXITY_API_KEY=
CHATGPT_API_KEY=

# Google
GOOGLE_API_KEY=

# Apify
APIFY_USER_ID=
APIFY_API_KEY=

# Supabase / ingest tokens
STOCK_INGEST_TOKEN=
LEAD_INGEST_KEY=
CHIKARA_REALMS_SECRET=

# Lovable (optional)
LOVABLE_API_KEY=
LOVABLE_WORKSPACE_ID=
LOVABLE_CREDIT_THRESHOLD=5
```

Never commit `.env` or paste real keys into documentation.

## 6. Understand import paths and working directories

Most scripts add the repo root to `sys.path` automatically. A few behaviors differ:

| Run from | Scripts |
|----------|---------|
| **Repo root** | `stock_analyzer` (reads `scripts/stock_analyzer/previous_run_date.txt`) |
| **Script folder** | `blog_automation`, `leadgen`, `lead_automation`, `json_formatter`, `lovable_automation`, `webhook_manager` |
| **Either** | `clip_generator`, `montage_builder` (paths via `--base-dir` or `MOTO_VIDS_BASE`) |

In CI, stock analysis uses:

```bash
PYTHONPATH=$GITHUB_WORKSPACE python scripts/stock_analyzer/stock_analyzer.py
```

Locally from repo root:

```bash
python scripts/stock_analyzer/stock_analyzer.py
```

## 7. Optional: FFmpeg for video scripts

[`clip_generator`](../scripts/video_editing/clip_generator.py) and [`montage_builder`](../scripts/video_editing/montage_builder.py) require `ffmpeg` and `ffprobe` on your PATH.

- **Windows:** Install from [ffmpeg.org](https://ffmpeg.org/download.html) or `winget install ffmpeg`
- **macOS:** `brew install ffmpeg`
- **Linux:** `sudo apt install ffmpeg`

## 8. Verify the setup

**API manager (test mode, no API keys required):**

```bash
python helper_scripts/api_manager/api_manager.py
```

**Unit tests (from repo root):**

```bash
python -m unittest unittests.lead_automation.test_leadgen
```

See [testing/unittests.md](testing/unittests.md) for details.

## 9. Run a script

Check the per-script doc in [scripts/](scripts/) for exact commands, config files, and required env vars before running automation that calls paid APIs.

## Troubleshooting

- **ModuleNotFoundError for `helper_scripts`:** Run from the correct working directory or set `PYTHONPATH` to the repo root.
- **FileNotFoundError for JSON configs:** Many scripts open files relative to the current directory—`cd` into the script folder first.
- **Missing API key errors:** Confirm the variable name in `.env` matches what `APIManager` expects (see [helper_scripts/api_manager.md](helper_scripts/api_manager.md)).
