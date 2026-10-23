"""The generated repo map must match the current imports."""
import unittest
from pathlib import Path

from scripts.repo_map.generate import check, generated_documents


class RepoMapTests(unittest.TestCase):
    def test_generated_files_match_sources(self):
        self.assertEqual(check(), [])

    def test_leadgen_diagram_includes_the_split_modules(self):
        text = generated_documents()["leadgen.md"]
        self.assertIn("flowchart LR", text)
        self.assertIn("lead_pipeline.py", text)
        self.assertIn("places_api.py", text)

    def test_pages_renderer_uses_mermaid_blocks(self):
        root = Path(__file__).resolve().parents[2]
        overview = (root / "documentation" / "repo-map" / "overview.md").read_text(encoding="utf-8")
        self.assertIn("generate.py", overview)
