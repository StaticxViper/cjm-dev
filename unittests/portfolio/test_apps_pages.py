"""The apps hub stays in cjm-dev and renders into the shared site shell."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "portfolio"))

from pages_shell import SOURCE_NOTE, markdown_to_html, render_nav  # noqa: E402
from render_apps import load_catalog, render_apps, validate_catalog  # noqa: E402
from scripts.repo_map.generate import write_pages  # noqa: E402


class AppsHubTests(unittest.TestCase):
    def test_source_of_truth_is_this_repo(self):
        readme = (ROOT / "documentation" / "apps" / "README.md").read_text(encoding="utf-8")
        self.assertIn(SOURCE_NOTE, readme)
        self.assertIn("submodule", readme.lower())
        workflow = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
        self.assertIn("documentation/apps/**", workflow)
        self.assertIn("python portfolio/build.py", workflow)
        self.assertIn("scripts/repo_map/generate.py --pages", workflow)

    def test_catalog_links_are_references_only(self):
        catalog = load_catalog()
        validate_catalog(catalog)
        self.assertEqual(catalog["sourceNote"], SOURCE_NOTE)
        for project in catalog["projects"]:
            github = project.get("github")
            if not github:
                continue
            self.assertTrue(github["url"].startswith("https://github.com/"))
            self.assertNotIn("submodule", github["url"])

    def test_rejected_repo_link_fails_the_build(self):
        catalog = json.loads(json.dumps(load_catalog()))
        catalog["projects"][0]["github"]["url"] = "https://example.com/not-github"
        with self.assertRaises(SystemExit):
            validate_catalog(catalog)

    def test_rendered_hub_has_how_it_works_and_changelog(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "apps"
            count = render_apps(dest)
            index = (dest / "index.html").read_text(encoding="utf-8")
            how = (dest / "chikara" / "how-it-works.html").read_text(encoding="utf-8")
            changelog = (dest / "chikara" / "changelog.html").read_text(encoding="utf-8")
        self.assertGreaterEqual(count, 4)
        self.assertIn(SOURCE_NOTE, index)
        self.assertIn('href="../repo-map/index.html"', index)
        self.assertIn("Personal admin dashboard", index)
        self.assertIn("Apps — CJ Moulton", index)
        self.assertIn('href="personal-admin/index.html"', index)
        self.assertNotIn("MV LLC", index)
        self.assertNotIn("Moulton Ventures", index)
        self.assertNotIn("mv-llc", index)
        self.assertNotIn("— Moulton", index)
        self.assertIn("Property Portal", index)
        self.assertIn("class=\"mermaid\"", how)
        self.assertIn("How it works", how)
        self.assertIn("Changelog", changelog)
        self.assertIn("https://github.com/StaticxViper/chikararealms", how)
        self.assertIn("https://chikararealms.com", how)
        self.assertNotIn("git submodule", how.lower())

    def test_site_links_and_nav_include_the_map(self):
        self.assertIn("apps/index.html", render_nav("home", 0))
        self.assertIn("repo-map/index.html", render_nav("home", 0))
        html = markdown_to_html("[Map](site:repo-map/repo.html)\n\n- [Flow](data-flow.md)", depth=2)
        self.assertIn('href="../../repo-map/repo.html"', html)
        self.assertIn('href="data-flow.html"', html)

    def test_repo_map_pages_use_the_site_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "repo-map"
            write_pages(dest)
            index = (dest / "index.html").read_text(encoding="utf-8")
            overview = (dest / "overview.html").read_text(encoding="utf-8")
            data_flow = (dest / "data-flow.html").read_text(encoding="utf-8")
        self.assertIn("../site.css", index)
        self.assertIn(SOURCE_NOTE, index)
        self.assertIn('href="../apps/index.html"', index)
        self.assertIn('aria-current="page"', overview)
        self.assertIn('class="mermaid"', data_flow)
        self.assertIn('theme: "dark"', data_flow)
        self.assertIn("Repo map — CJ Moulton", index)
        self.assertNotIn("Moulton Ventures", index)
        self.assertNotIn("— Moulton", index)
        self.assertNotIn("LLC", overview)
