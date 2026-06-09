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
6. **Run scripts from the correct directory**—some require their script folder, others (like stock analyzer) require the repo root. See the [working directory cheat sheet](documentation/README.md#working-directory-cheat-sheet).
7. **Optional:** Install [FFmpeg](https://ffmpeg.org/download.html) for video editing scripts (`clip_generator`, `montage_builder`).
8. **Verify setup:** `python helper_scripts/api_manager/api_manager.py` (test mode) or `python -m unittest unittests.lead_automation.test_leadgen`

Full details: [documentation/setup.md](documentation/setup.md)

## Documentation

Per-script guides (purpose, configuration, usage, and how each tool works) live in [`documentation/`](documentation/).

- **[Documentation index](documentation/README.md)** — links to every script, helper module, and test guide
- **[Setup guide](documentation/setup.md)** — detailed new-environment instructions
- **[Unit tests](documentation/testing/unittests.md)** — how to run tests

## Current Focus

- Building tools that solve real-world problems.
- Sharpening software engineering fundamentals through consistent project work.
- Expanding depth in automation, scripting, and clean project structure.

## About Me

Chris "CJ" Moulton  
Software Engineer  
Masters in Computer Science, Minor in Cyber Security (Felician University)

LinkedIn: [www.linkedin.com/in/moultonc](https://www.linkedin.com/in/moultonc)

## Roadmap

- Expand automation coverage and CI for additional scripts.
- Continue refining shared helpers (`api_manager`, logging) across projects.
