"""Store scrapers for the grocery price sync."""

from grocery.scrapers.amazon import AmazonScraper
from grocery.scrapers.costco import CostcoScraper
from grocery.scrapers.shoprite import ShopRiteScraper

SCRAPERS = {
    "amazon": AmazonScraper,
    "costco": CostcoScraper,
    "shoprite": ShopRiteScraper,
}

__all__ = ["AmazonScraper", "CostcoScraper", "SCRAPERS", "ShopRiteScraper"]
