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
    "scripts/lead_automation/crm_enrich_robots.py",
    "helper_scripts/__init__.py",
    "helper_scripts/http/__init__.py",
    "helper_scripts/http/client.py",
)


def main():
    if BUNDLE.exists():
        shutil.rmtree(BUNDLE)
    for relative in FILES:
        source = ROOT / relative
        target = BUNDLE / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    print(f"Wrote {len(FILES)} files to {BUNDLE}")


if __name__ == "__main__":
    main()
