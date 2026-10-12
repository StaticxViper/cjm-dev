"""Quantity and currency parsing."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from grocery.parser import PriceError, parse_price, parse_size  # noqa: E402


class TestParsePrice(unittest.TestCase):
    def test_currency_and_commas(self):
        self.assertAlmostEqual(parse_price("$14.99"), 14.99)
        self.assertAlmostEqual(parse_price("$1,299.00"), 1299.00)
        self.assertAlmostEqual(parse_price(4.99), 4.99)

    def test_empty_is_none(self):
        self.assertIsNone(parse_price(None))
        self.assertIsNone(parse_price(""))
        self.assertIsNone(parse_price("   "))

    def test_bounds(self):
        self.assertAlmostEqual(parse_price(10000), 10000.0)
        for value in (0, -1, 10000.01, float("nan"), float("inf"), "free", True):
            with self.assertRaises(PriceError):
                parse_price(value)


class TestParseSize(unittest.TestCase):
    def test_units(self):
        self.assertEqual(parse_size("1.5 lbs"), {"size_value": 1.5, "size_unit": "lb"})
        self.assertEqual(parse_size("128 fl oz"), {"size_value": 128.0, "size_unit": "fl oz"})
        self.assertEqual(parse_size("24 ct"), {"size_value": 24.0, "size_unit": "ct"})
        self.assertEqual(parse_size("1 gal"), {"size_value": 1.0, "size_unit": "gal"})
        self.assertEqual(parse_size("16 oz"), {"size_value": 16.0, "size_unit": "oz"})
        self.assertEqual(parse_size("6 each"), {"size_value": 6.0, "size_unit": "each"})

    def test_multipack(self):
        self.assertEqual(parse_size("Pack of 2, 32 oz each"), {"size_value": 64.0, "size_unit": "oz"})
        self.assertEqual(parse_size("2 x 32 oz"), {"size_value": 64.0, "size_unit": "oz"})
        self.assertEqual(parse_size("Pack of 12"), {"size_value": 12.0, "size_unit": "ct"})

    def test_missing_size(self):
        self.assertIsNone(parse_size(None))
        self.assertIsNone(parse_size(""))
        self.assertIsNone(parse_size("about a pound"))


if __name__ == "__main__":
    unittest.main()
