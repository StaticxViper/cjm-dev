"""
Unit tests for Apify run dataset-ID extraction.

Run from repo root:
    python -m unittest unittests.helper_scripts.test_api_manager_dataset_id
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from helper_scripts.api_manager.api_manager import _extract_dataset_id


class _V3Run:
    """Stand-in for apify-client >= 3 typed Run: snake_case attrs, not subscriptable."""

    def __init__(self, dataset_id: str):
        self.default_dataset_id = dataset_id

    def __iter__(self):
        yield ('default_dataset_id', self.default_dataset_id)


class ExtractDatasetIdTests(unittest.TestCase):
    def test_v2_dict_camel_case(self):
        self.assertEqual(_extract_dataset_id({'defaultDatasetId': 'ds_v2'}), 'ds_v2')

    def test_dict_from_v3_model_uses_snake_case(self):
        run = _V3Run('ds_from_dict')
        self.assertEqual(_extract_dataset_id(dict(run)), 'ds_from_dict')

    def test_v3_run_object_attribute(self):
        self.assertEqual(_extract_dataset_id(_V3Run('ds_v3')), 'ds_v3')

    def test_v3_run_via_model_dump(self):
        class DumpOnly:
            def model_dump(self):
                return {'default_dataset_id': 'ds_dump'}

        self.assertEqual(_extract_dataset_id(DumpOnly()), 'ds_dump')

    def test_simple_namespace(self):
        self.assertEqual(
            _extract_dataset_id(SimpleNamespace(default_dataset_id='ds_ns')),
            'ds_ns',
        )

    def test_none_raises(self):
        with self.assertRaises(RuntimeError):
            _extract_dataset_id(None)

    def test_empty_dict_raises(self):
        with self.assertRaises(RuntimeError):
            _extract_dataset_id({})

    def test_old_ci_pattern_breaks_on_v3_run(self):
        """The previous GitHub Actions fix, dict(run)['defaultDatasetId'], fails on v3."""
        run = _V3Run('ds_v3')
        with self.assertRaises(KeyError):
            dict(run)['defaultDatasetId']
        with self.assertRaises(TypeError):
            run['defaultDatasetId']  # type: ignore[index]


if __name__ == '__main__':
    unittest.main()
