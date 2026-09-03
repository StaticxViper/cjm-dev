"""
Unit tests for scripts/zillow_automation/property_listing_gen.py

Run from repo root:
    python -m unittest unittests.zillow_automation.test_property_listing_gen
"""
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPT_DIR = _REPO_ROOT / "scripts" / "zillow_automation"


def _import_listing_gen():
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    if "property_listing_gen" in sys.modules:
        return importlib.reload(sys.modules["property_listing_gen"])
    return importlib.import_module("property_listing_gen")


def _get_listing_gen_or_skip():
    _prev = os.getcwd()
    try:
        os.chdir(_SCRIPT_DIR)
        if str(_SCRIPT_DIR) not in sys.path:
            sys.path.insert(0, str(_SCRIPT_DIR))
        return _import_listing_gen(), None
    except Exception as e:
        return None, e
    finally:
        os.chdir(_prev)


LISTING_GEN, _IMPORT_ERR = _get_listing_gen_or_skip()
SKIP = unittest.skipIf(
    LISTING_GEN is None,
    f"property_listing_gen import failed (install project deps): {_IMPORT_ERR!r}",
)

SAMPLE_URL = "https://www.zillow.com/homedetails/125-Perry-St-PHE-New-York-NY-10014/458671486_zpid/"
SAMPLE_URL_2 = "https://www.zillow.com/homedetails/17-Zelma-Dr-Greenville-SC-29617/11026031_zpid/"


def _item(**overrides):
    base = {
        "zpid": "458671486",
        "propertyUrl": SAMPLE_URL,
        "listingStatus": "forSale",
    }
    base.update(overrides)
    return base


@SKIP
class TestExtractPropertyUrls(unittest.TestCase):
    def test_reads_property_url(self):
        self.assertEqual(
            LISTING_GEN.extract_property_urls([_item()]),
            [SAMPLE_URL],
        )

    def test_falls_back_to_detail_url(self):
        self.assertEqual(
            LISTING_GEN.extract_property_urls([{"detailUrl": SAMPLE_URL}]),
            [SAMPLE_URL],
        )

    def test_skips_items_without_url(self):
        self.assertEqual(
            LISTING_GEN.extract_property_urls([{"zpid": "1"}, _item()]),
            [SAMPLE_URL],
        )

    def test_skips_non_zillow_urls(self):
        self.assertEqual(
            LISTING_GEN.extract_property_urls([{"propertyUrl": "https://example.com/listing"}]),
            [],
        )

    def test_dedupes_preserving_order(self):
        items = [_item(), _item(propertyUrl=SAMPLE_URL_2), _item()]
        self.assertEqual(
            LISTING_GEN.extract_property_urls(items),
            [SAMPLE_URL, SAMPLE_URL_2],
        )

    def test_unwraps_items_dict(self):
        self.assertEqual(
            LISTING_GEN.extract_property_urls({"items": [_item()]}),
            [SAMPLE_URL],
        )

    def test_empty_or_none_returns_empty_list(self):
        self.assertEqual(LISTING_GEN.extract_property_urls(None), [])
        self.assertEqual(LISTING_GEN.extract_property_urls([]), [])
        self.assertEqual(LISTING_GEN.extract_property_urls("nope"), [])


@SKIP
class TestNormalizeSearchInput(unittest.TestCase):
    def test_accepts_example_input(self):
        result = LISTING_GEN.normalize_search_input(dict(LISTING_GEN.DEFAULT_SEARCH_INPUT))
        self.assertEqual(result["zipCodes"], ["14010", "07306"])
        self.assertEqual(result["priceMin"], 100000)

    def test_coerces_zip_codes_to_strings(self):
        result = LISTING_GEN.normalize_search_input({"zipCodes": [14010, "07306"]})
        self.assertEqual(result["zipCodes"], ["14010", "07306"])

    def test_accepts_single_zip_string(self):
        result = LISTING_GEN.normalize_search_input({"zipCodes": "07306"})
        self.assertEqual(result["zipCodes"], ["07306"])

    def test_rejects_missing_zip_codes(self):
        with self.assertRaises(ValueError):
            LISTING_GEN.normalize_search_input({})

    def test_rejects_empty_zip_codes(self):
        with self.assertRaises(ValueError):
            LISTING_GEN.normalize_search_input({"zipCodes": ["", "  "]})

    def test_rejects_non_object(self):
        with self.assertRaises(ValueError):
            LISTING_GEN.normalize_search_input([{"zipCodes": ["07306"]}])


@SKIP
class TestLoadAndSave(unittest.TestCase):
    def test_load_search_input_from_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.json"
            path.write_text(json.dumps({"zipCodes": ["07306"], "resultsLimit": 5}), encoding="utf-8")
            result = LISTING_GEN.load_search_input(path)
            self.assertEqual(result["zipCodes"], ["07306"])
            self.assertEqual(result["resultsLimit"], 5)

    def test_save_property_urls_writes_json_array(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out" / "property_urls.json"
            LISTING_GEN.save_property_urls([SAMPLE_URL, SAMPLE_URL_2], path)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), [SAMPLE_URL, SAMPLE_URL_2])
            self.assertFalse(path.with_name("property_urls.json.tmp").exists())


@SKIP
class TestResolveSearchInput(unittest.TestCase):
    def test_cli_overrides_file_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.json"
            path.write_text(
                json.dumps(LISTING_GEN.DEFAULT_SEARCH_INPUT),
                encoding="utf-8",
            )
            args = LISTING_GEN.parse_args([
                "--input", str(path),
                "--zip-codes", "19103",
                "--price-min", "200000",
                "--results-limit", "3",
                "--for-rent",
                "--no-for-sale-by-agent",
            ])
            result = LISTING_GEN.resolve_search_input(args)
            self.assertEqual(result["zipCodes"], ["19103"])
            self.assertEqual(result["priceMin"], 200000)
            self.assertEqual(result["resultsLimit"], 3)
            self.assertTrue(result["forRent"])
            self.assertFalse(result["forSaleByAgent"])
            self.assertFalse(result["sold"])


@SKIP
class TestGenerateListings(unittest.TestCase):
    def test_runs_actor_and_writes_urls(self):
        mock_api = MagicMock()
        mock_api.run_apify.return_value = [_item(), _item(propertyUrl=SAMPLE_URL_2)]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "property_urls.json"
            urls = LISTING_GEN.generate_listings(
                {"zipCodes": ["07306"], "resultsLimit": 10},
                path,
                api=mock_api,
            )
            self.assertEqual(urls, [SAMPLE_URL, SAMPLE_URL_2])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), urls)
        mock_api.run_apify.assert_called_once_with(
            actor="Zillow ZIP Search",
            input={"zipCodes": ["07306"], "resultsLimit": 10},
        )

    def test_missing_api_key_skips_run(self):
        with patch.object(LISTING_GEN, "APIFY_API_KEY", None), \
             patch.object(LISTING_GEN, "APIManager") as mock_api_cls:
            urls = LISTING_GEN.generate_listings({"zipCodes": ["07306"]}, "unused.json")
        self.assertEqual(urls, [])
        mock_api_cls.assert_not_called()

    def test_main_returns_error_without_api_key(self):
        with patch.object(LISTING_GEN, "APIFY_API_KEY", None):
            self.assertEqual(LISTING_GEN.main(["--zip-codes", "07306"]), 1)


if __name__ == "__main__":
    unittest.main()
