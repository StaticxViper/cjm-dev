# cjm-dev

Core repository for projects, automation, and game-mod development by Chris Moulton (StaticxViper).

## What This Repo Is

`cjm-dev` is my personal development hub: a place to build practical tools, test ideas quickly, and keep growing as an engineer through real projects.

## What You Will Find Here

- Automation scripts in [`scripts/`](scripts/) that reduce repetitive work and speed up daily workflows.
- Shared helpers in [`helper_scripts/`](helper_scripts/) used across automation and experiments.
- Game modding projects (Civilization-focused) built for both creativity and technical challenge.
- Unit tests in [`unittests/`](unittests/) that help validate and maintain script quality over time.

## Setting Up a New Environment

1. **Clone** the repository and `cd` into it.
2. **Install Python 3.12+** and verify with `python --version`.
3. **Create a virtual environment:** `python -m venv .venv`, then activate it (`.venv\Scripts\Activate.ps1` on Windows, `source .venv/bin/activate` on macOS/Linux).
4. **Install dependencies:** `pip install -r requirements/requirements.txt`
5. **Create a `.env` file** at the repo root with API keys for the scripts you plan to run (see [documentation/README.md](documentation/README.md#environment-variables)). The file is gitignored—never commit secrets.
6. **Run scripts from the correct directory**—some require their script folder, others (like stock analyzer) require the repo root. See the [working directory cheat sheet](documentation/README.md#working-directory-cheat-sheet). To list every registered script and run one without changing directories, use `python -m scripts.script_manager list` and `python -m scripts.script_manager run <name>`. Details: [documentation/scripts/script_manager.md](documentation/scripts/script_manager.md).
7. **Optional:** Install [FFmpeg](https://ffmpeg.org/download.html) for video editing scripts (`clip_generator`, `montage_builder`).
8. **Verify setup:** `python helper_scripts/api_manager/api_manager.py` (test mode) or `python -m unittest unittests.lead_automation.test_leadgen`

Full details: [documentation/setup.md](documentation/setup.md)

## Repository layout

- [`scripts/`](scripts/) holds one folder per tool. Each folder README covers purpose, inputs, outputs, a local run command, Script Manager or GitHub Actions, and secrets.
- [`helper_scripts/`](helper_scripts/) holds shared modules: HTTP (`http`), HTML and URL signals (`web`), names and phones (`text`), Maps identity (`maps`), CRM JSON-RPC (`crm`), Playwright pacing (`browser`), plus [`api_manager`](helper_scripts/api_manager/) and [`utils/logger`](helper_scripts/utils/logger/).
- [`unittests/`](unittests/) mirrors those tools.
- [`documentation/`](documentation/) has the longer per-script guides.
- [`portfolio/`](portfolio/) is the Moulton site. The repo map is a separate Pages path and is not in that site's nav.

### Main tools

| Tool | Folder | How to run |
|------|--------|------------|
| Lead generation | [`scripts/lead_automation/`](scripts/lead_automation/) | `python -m scripts.script_manager run leadgen` |
| Opportunity finder | [`scripts/opp_finder_v2/`](scripts/opp_finder_v2/) | `python -m opp_finder_v2` from `scripts/` |
| Grocery prices | [`scripts/grocery/`](scripts/grocery/) | `python -m grocery.scraper` from `scripts/` |
| City data | [`scripts/city_data/`](scripts/city_data/) | `python -m scripts.script_manager run city-data` |
| Zillow URL search | [`scripts/zillow_automation/`](scripts/zillow_automation/) | `python -m scripts.script_manager run property-listing-gen` |
| Script Manager | [`scripts/script_manager/`](scripts/script_manager/) | `python -m scripts.script_manager list` |
| Apify Actors | [`scripts/apify-scripts/`](scripts/apify-scripts/) | `apify run` inside the Actor folder |

## Documentation

Per-script guides live in [`documentation/`](documentation/). Folder READMEs are the short version.

- **[Documentation index](documentation/README.md)** — links to every script, helper module, folder README, and test guide
- **[Setup guide](documentation/setup.md)** — detailed new-environment instructions
- **[Unit tests](documentation/testing/unittests.md)** — how to run tests
- **[Repo map](https://staticxviper.github.io/cjm-dev/repo-map/)** — import and call diagrams. Source: [`documentation/repo-map/`](documentation/repo-map/). Regenerate with `python scripts/repo_map/generate.py` and check drift with `python scripts/repo_map/generate.py --check`.

## Current Focus

- Building tools that solve real-world problems.
- Sharpening software engineering fundamentals through consistent project work.
- Expanding depth in automation, scripting, and clean project structure.

## Portfolio

The Moulton site is in [`portfolio/`](portfolio/). Edit [`portfolio/content.json`](portfolio/content.json) to choose which websites, apps, and scripts are shown, then build and publish with GitHub Pages. Details: [portfolio/README.md](portfolio/README.md).

## About Me

Chris "CJ" Moulton  
Software Engineer  
Masters in Computer Science, Minor in Cyber Security (Felician University)

LinkedIn: [www.linkedin.com/in/moultonc](https://www.linkedin.com/in/moultonc)

## Roadmap

- Expand automation coverage and CI for additional scripts.
- Continue refining shared helpers (`api_manager`, logging) across projects.
