"""Copy the modules this Actor imports into platform_bundle.

Apify rejects a Docker context outside the Actor directory, so the image
cannot COPY the rest of the repo. Run this from the Actor directory before
apify push. The copies are what the image runs.
"""

from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[3]
BUNDLE = Path(__file__).resolve().parent / "platform_bundle"
FILES = (
    "scripts/apify-scripts/runtime.py",
    "scripts/apify-scripts/access.py",
    "scripts/zillow_automation/__init__.py",
    "scripts/zillow_automation/zillow_agents.py",
    "scripts/zillow_automation/zillow_enrich.py",
    "scripts/zillow_automation/zillow_parse.py",
    "scripts/lead_automation/crm_enrich_match.py",
    "scripts/lead_automation/email_discovery.py",
    "scripts/lead_automation/leadenrich.py",
    "scripts/lead_automation/leadenrich_playwright.py",
    "scripts/lead_automation/website_quality.py",
    "scripts/opp_finder_v2/__init__.py",
    "scripts/opp_finder_v2/browser/__init__.py",
    "scripts/opp_finder_v2/browser/detection.py",
    "scripts/opp_finder_v2/models.py",
    "scripts/opp_finder_v2/parsing.py",
    "scripts/opp_finder_v2/politeness.py",
    "helper_scripts/__init__.py",
    "helper_scripts/api_manager/__init__.py",
    "helper_scripts/api_manager/api_manager.py",
    "helper_scripts/browser/__init__.py",
    "helper_scripts/browser/backoff.py",
    "helper_scripts/browser/google_session.py",
    "helper_scripts/browser/route_block.py",
    "helper_scripts/http/__init__.py",
    "helper_scripts/http/client.py",
    "helper_scripts/text/__init__.py",
    "helper_scripts/text/names.py",
    "helper_scripts/text/phones.py",
    "helper_scripts/utils/__init__.py",
    "helper_scripts/utils/logger/__init__.py",
    "helper_scripts/utils/logger/logger.py",
    "helper_scripts/web/__init__.py",
    "helper_scripts/web/html_signals.py",
    "helper_scripts/web/urls.py",
)


def main():
    if BUNDLE.exists():
        shutil.rmtree(BUNDLE)
    for relative in FILES:
        source = ROOT / relative
        if not source.is_file():
            raise SystemExit(f"Missing {source}")
        target = BUNDLE / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    print(f"Wrote {len(FILES)} files to {BUNDLE}")


if __name__ == "__main__":
    main()
