"""Pull linked grocery items, scrape prices, and push them in batches of 20."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

if __package__ in {None, ""}:
    _SCRIPTS = Path(__file__).resolve().parents[1]
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))

import httpx

from grocery.config import ConfigError, Settings, load_settings
from grocery.models import ProductRecord
from grocery.parser import PriceError, parse_price
from grocery.scrapers.amazon import AmazonScraper
from grocery.scrapers.base import BrowserSession
from grocery.scrapers.costco import CostcoScraper
from grocery.scrapers.shoprite import ShopRiteScraper

API_FIELDS = (
    "item_store_id",
    "price",
    "regular_price",
    "size_value",
    "size_unit",
    "product_url",
    "source",
    "force",
)
_SELECT = (
    "id,product_url,pack_price,regular_price,size_value,size_unit,"
    "item_id,store_id,shopping_stores!inner(name,provider),shopping_items(name,upc)"
)
_STORES = ("shoprite", "costco", "amazon")


class SyncError(Exception):
    """A pull or push call failed before per-item results were available."""


def to_push_item(item_store_id: str, product: ProductRecord, *, force: bool) -> dict:
    price = parse_price(product.price)
    if price is None:
        raise PriceError("missing price")
    item = {
        "item_store_id": item_store_id,
        "price": price,
        "product_url": product.product_url,
        "source": "script",
        "force": bool(force),
    }
    if product.regular_price is not None:
        try:
            regular = parse_price(product.regular_price)
        except PriceError:
            regular = None
        if regular is not None:
            item["regular_price"] = regular
    if product.size_value is not None and product.size_unit:
        item["size_value"] = float(product.size_value)
        item["size_unit"] = product.size_unit
    return item


def api_item(payload: dict) -> dict:
    return {key: payload[key] for key in API_FIELDS if key in payload}


def batch_prices(prices: list[dict], size: int = 20) -> list[list[dict]]:
    step = size if size and size > 0 else 20
    return [prices[index : index + step] for index in range(0, len(prices), step)]


def normalize_link(row: dict) -> dict:
    store = row.get("shopping_stores") or {}
    item = row.get("shopping_items") or {}
    if isinstance(store, list):
        store = store[0] if store else {}
    if isinstance(item, list):
        item = item[0] if item else {}
    return {
        "item_store_id": row.get("id"),
        "product_url": row.get("product_url"),
        "provider": str(store.get("provider") or "").lower(),
        "store_name": store.get("name"),
        "item_name": item.get("name"),
        "upc": item.get("upc"),
        "pack_price": row.get("pack_price"),
        "regular_price": row.get("regular_price"),
        "size_value": row.get("size_value"),
        "size_unit": row.get("size_unit"),
    }


def extract_result_rows(body: object) -> list:
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("results", "prices", "data"):
            rows = body.get(key)
            if isinstance(rows, list):
                return rows
    return []


def _error_message(body: object) -> str:
    if isinstance(body, dict):
        for key in ("message", "error", "msg"):
            value = body.get(key)
            if value:
                return str(value)
    if isinstance(body, str) and body.strip():
        return body.strip()
    return ""


def _with_status(item: dict, status: str, message: str) -> dict:
    outcome = dict(item)
    outcome["status"] = status
    if message:
        outcome["message"] = message
    return outcome


def interpret_push_response(body: object, sent: list[dict], *, http_status: int) -> list[dict]:
    if http_status >= 400:
        message = _error_message(body) or f"http_{http_status}"
        return [_with_status(item, "error", message) for item in sent]
    rows = extract_result_rows(body)
    if not rows:
        return [_with_status(item, "ok", "") for item in sent]
    sent_by_id = {item.get("item_store_id"): item for item in sent}
    used: set = set()
    outcomes: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item_id = row.get("item_store_id")
        base = sent_by_id.get(item_id, {"item_store_id": item_id})
        status = str(row.get("status") or "").lower()
        if status not in {"ok", "flagged", "error"}:
            status = "error" if row.get("error") else "ok"
        message = str(row.get("message") or row.get("error") or "")
        outcomes.append(_with_status(base, status, message))
        if item_id:
            used.add(item_id)
    for item in sent:
        if item.get("item_store_id") not in used:
            outcomes.append(_with_status(item, "ok", ""))
    return outcomes


def sync_records(
    records: list[dict],
    scrape,
    push,
    *,
    force: bool,
    dry_run: bool,
    batch_size: int,
) -> list[dict]:
    outcomes: list[dict] = []
    pending: list[dict] = []
    for record in records:
        url = record.get("product_url")
        item_id = record.get("item_store_id")
        if not url:
            outcomes.append(
                {
                    "item_store_id": item_id,
                    "status": "skipped",
                    "reason": "no_url",
                    "name": record.get("item_name"),
                }
            )
            continue
        product = scrape(record)
        name = product.name or record.get("item_name")
        if product.error or product.price is None:
            outcomes.append(
                {
                    "item_store_id": item_id,
                    "status": "failed",
                    "product_url": url,
                    "reason": product.error or "no_price",
                    "name": name,
                }
            )
            continue
        try:
            payload = to_push_item(item_id, product, force=force)
        except PriceError as exc:
            outcomes.append(
                {
                    "item_store_id": item_id,
                    "status": "failed",
                    "product_url": url,
                    "reason": str(exc),
                    "name": name,
                }
            )
            continue
        payload["name"] = name
        if dry_run:
            outcomes.append({**payload, "status": "dry_run"})
            continue
        pending.append(payload)
    for batch in batch_prices(pending, batch_size):
        status, body = push([api_item(item) for item in batch])
        outcomes.extend(interpret_push_response(body, batch, http_status=status))
    return outcomes


class GroceryClient:
    def __init__(self, settings: Settings, http: httpx.Client | None = None):
        self.settings = settings
        self._http = http or httpx.Client(timeout=settings.timeout_ms / 1000)
        self._owns_http = http is None

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self.settings.anon_key,
            "Authorization": f"Bearer {self.settings.service_role_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(self, method: str, path: str, *, params=None, json_body=None) -> httpx.Response:
        if not self.settings.supabase_url:
            raise ConfigError("Missing SUPABASE_URL")
        try:
            return self._http.request(
                method,
                self.settings.supabase_url + path,
                params=params,
                json=json_body,
                headers=self._headers(),
            )
        except httpx.HTTPError as exc:
            raise SyncError(str(exc)) from exc

    def fetch_links(self, provider: str | None = None) -> list[dict]:
        rows: list[dict] = []
        offset = 0
        page_size = 1000
        while True:
            params: dict[str, object] = {
                "select": _SELECT,
                "limit": page_size,
                "offset": offset,
            }
            if provider:
                params["shopping_stores.provider"] = f"eq.{provider}"
            response = self._request("GET", "/rest/v1/shopping_item_stores", params=params)
            if response.status_code >= 400:
                raise SyncError(f"shopping_item_stores http_{response.status_code}")
            batch = response.json()
            if not isinstance(batch, list):
                raise SyncError("unexpected shopping_item_stores response")
            rows.extend(normalize_link(row) for row in batch)
            if len(batch) < page_size:
                break
            offset += page_size
        return rows

    def push_prices(self, prices: list[dict]) -> tuple[int, object]:
        response = self._request(
            "POST",
            "/functions/v1/grocery-lookup",
            json_body={"action": "push_prices", "prices": prices},
        )
        try:
            body = response.json()
        except ValueError:
            body = {"message": response.text}
        return response.status_code, body


def provider_for_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "amazon." in host or host.startswith("amzn."):
        return "amazon"
    if "costco." in host:
        return "costco"
    if "shoprite." in host or "wakefern." in host:
        return "shoprite"
    raise ConfigError(f"unsupported store URL: {url}")


def build_scraper(provider: str, session: BrowserSession, settings: Settings):
    if provider == "shoprite":
        return ShopRiteScraper(
            session,
            zip_code=settings.shoprite_zip,
            storage_state=settings.storage_state_path,
        )
    if provider == "costco":
        return CostcoScraper(session)
    if provider == "amazon":
        return AmazonScraper(session)
    raise ConfigError(f"unsupported store: {provider}")


def open_session(settings: Settings, *, headless: bool, provider: str | None = None) -> BrowserSession:
    storage = None
    path = settings.storage_state_path
    if provider == "shoprite" and path.is_file():
        storage = str(path)
    return BrowserSession(
        headless=headless,
        timeout_ms=settings.timeout_ms,
        min_delay_s=settings.min_delay_s,
        storage_state=storage,
    )


def _money(value: object) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _size(row: dict) -> str:
    value = row.get("size_value")
    unit = row.get("size_unit")
    if value is None or not unit:
        return ""
    number = int(value) if float(value).is_integer() else value
    return f"{number} {unit}"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def format_row(cells: list[str]) -> str:
        return "  ".join(cell.ljust(widths[index]) for index, cell in enumerate(cells))

    lines = [format_row(headers), format_row(["-" * width for width in widths])]
    lines.extend(format_row(row) for row in rows)
    return "\n".join(lines)


def format_summary(outcomes: list[dict]) -> str:
    groups = {"ok": [], "flagged": [], "failed": [], "skipped": [], "dry_run": []}
    for row in outcomes:
        status = row.get("status")
        if status == "error":
            status = "failed"
        groups.get(status, groups["failed"]).append(row)
    sections = [
        ("OK", "ok", ("item_store_id", "name", "price", "regular", "size", "url")),
        ("Flagged outliers", "flagged", ("item_store_id", "name", "price", "message", "url")),
        ("Failed URLs", "failed", ("name", "url", "reason")),
        ("Dry run", "dry_run", ("item_store_id", "name", "price", "regular", "size", "url")),
    ]
    blocks = [f"Skipped (no URL): {len(groups['skipped'])}"]
    for title, key, columns in sections:
        rows = groups[key]
        blocks.append(f"\n{title} ({len(rows)})")
        if not rows:
            continue
        table_rows = [_summary_cells(row, columns) for row in rows]
        blocks.append(_table(list(columns), table_rows))
    return "\n".join(blocks)


def _summary_cells(row: dict, columns: tuple[str, ...]) -> list[str]:
    cells = []
    for column in columns:
        if column == "price":
            cells.append(_money(row.get("price")))
        elif column == "regular":
            cells.append(_money(row.get("regular_price")))
        elif column == "size":
            cells.append(_size(row))
        elif column == "url":
            cells.append(str(row.get("product_url") or ""))
        elif column == "reason":
            cells.append(str(row.get("reason") or row.get("message") or row.get("status") or ""))
        elif column == "message":
            cells.append(str(row.get("message") or ""))
        elif column == "name":
            cells.append(str(row.get("name") or ""))
        else:
            cells.append(str(row.get(column) or ""))
    return cells


def format_products(products: list[ProductRecord]) -> str:
    rows = []
    for product in products:
        size = ""
        if product.size_value is not None and product.size_unit:
            number = int(product.size_value) if float(product.size_value).is_integer() else product.size_value
            size = f"{number} {product.size_unit}"
        rows.append(
            [
                product.name or "",
                _money(product.price),
                _money(product.regular_price),
                size,
                product.upc or "",
                product.asin or "",
                product.product_url or "",
                product.error or product.note or "",
            ]
        )
    return _table(
        ["name", "price", "regular", "size", "upc", "asin", "url", "note"],
        rows,
    )


def _exit_code(outcomes: list[dict]) -> int:
    if any(row.get("status") in {"failed", "error"} for row in outcomes):
        return 1
    return 0


def run_set_store(settings: Settings) -> int:
    session = open_session(settings, headless=False, provider="shoprite")
    try:
        page = session.page()
        page.goto("https://shop.shoprite.com/", wait_until="domcontentloaded")
        print("Choose your ShopRite store in the browser window, then press Enter.")
        try:
            input()
        except EOFError:
            print("No input available to confirm the store selection.", file=sys.stderr)
            return 2
        session.save_storage(settings.storage_state_path)
    finally:
        session.close()
    print(f"Saved store session to {settings.storage_state_path}")
    return 0


def run_test_url(settings: Settings, url: str) -> int:
    provider = provider_for_url(url)
    session = open_session(settings, headless=True, provider=provider)
    try:
        product = build_scraper(provider, session, settings).scrape_url(url)
    finally:
        session.close()
    print(format_products([product]))
    return 1 if product.error or product.price is None else 0


def run_search(settings: Settings, store: str, query: str) -> int:
    session = open_session(settings, headless=True, provider=store)
    try:
        hits = build_scraper(store, session, settings).search(query)
    finally:
        session.close()
    if len(hits) == 1 and hits[0].error and not hits[0].name:
        print(hits[0].error)
        return 1
    print(format_products(hits))
    return 1 if hits and all(hit.error for hit in hits) else 0


def run_sync(args: argparse.Namespace, settings: Settings) -> int:
    provider = args.store or None
    client = GroceryClient(settings)
    sessions: dict[str, BrowserSession] = {}
    scrapers: dict[str, object] = {}
    try:
        records = client.fetch_links(provider)
        print(f"Loaded {len(records)} linked item(s).")

        def scrape(record: dict) -> ProductRecord:
            name = (record.get("provider") or "").lower()
            label = record.get("item_name") or ""
            url = record.get("product_url") or ""
            print(f"Scraping {name} {label} {url}".strip())
            if name not in _STORES:
                return ProductRecord(product_url=url or None, error="unsupported_store")
            if name not in scrapers:
                sessions[name] = open_session(settings, headless=True, provider=name)
                scrapers[name] = build_scraper(name, sessions[name], settings)
            return scrapers[name].scrape_url(url)

        outcomes = sync_records(
            records,
            scrape,
            client.push_prices,
            force=args.force,
            dry_run=args.dry_run,
            batch_size=settings.batch_size,
        )
    finally:
        for session in sessions.values():
            session.close()
        client.close()
    print(format_summary(outcomes))
    return _exit_code(outcomes)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="grocery.sync",
        description="Scrape ShopRite, Costco, and Amazon prices and push them to grocery-lookup.",
    )
    parser.add_argument("--all", action="store_true", help="Sync every linked item")
    parser.add_argument("--store", choices=_STORES, help="Sync one store, or the store to search")
    parser.add_argument("--test-url", dest="test_url", help="Scrape one product URL and do not push")
    parser.add_argument("--search", help="Search a store and print results. Requires --store")
    parser.add_argument("--dry-run", action="store_true", help="Scrape linked items and skip the push")
    parser.add_argument("--force", action="store_true", help="Send force=true so flagged outliers can overwrite")
    parser.add_argument(
        "--set-shoprite-store",
        action="store_true",
        help="Open ShopRite, wait for you to pick a store, and save the browser session",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.set_shoprite_store:
            return run_set_store(load_settings(require_supabase=False))
        if args.test_url:
            return run_test_url(load_settings(require_supabase=False), args.test_url)
        if args.search:
            if not args.store:
                print("--search requires --store", file=sys.stderr)
                return 2
            return run_search(load_settings(require_supabase=False), args.store, args.search)
        if not args.all and not args.store:
            print("Choose --all, --store, --test-url, or --search.", file=sys.stderr)
            return 2
        return run_sync(args, load_settings(require_supabase=True))
    except (ConfigError, SyncError) as exc:
        print(str(exc), file=sys.stderr)
        return 2 if isinstance(exc, ConfigError) else 1


if __name__ == "__main__":
    raise SystemExit(main())
