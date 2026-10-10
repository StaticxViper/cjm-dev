"""Map Actor input onto the city-data CLI and shape dataset rows.

The CLI in scripts/city_data stays the source of truth. This module does not
launch a browser.
"""

from __future__ import annotations

try:
    from .runtime import iso_now, prepare_imports
except ImportError:
    from runtime import iso_now, prepare_imports

CITY_ROBOTS_URL = "https://www.city-data.com/robots.txt"


def _scraper():
    prepare_imports()
    import city_data_scraper as scraper
    return scraper


def _robots():
    prepare_imports()
    from crm_enrich_robots import robots_allowed
    return robots_allowed


def actor_input_to_config(actor_input):
    """Build a normalize_config dict from the Actor form.

    Accepts ``cities`` or a single ``city`` + ``state``. ``slug`` applies only
    to the single-city form.
    """
    scraper = _scraper()
    data = dict(actor_input or {})
    cities = data.get("cities")
    if not cities:
        city = str(data.get("city") or "").strip()
        state = str(data.get("state") or "").strip()
        if city or state:
            entry = {"city": city, "state": state}
            slug = str(data.get("slug") or "").strip()
            if slug:
                entry["slug"] = slug
            cities = [entry]
    config = {
        "cities": cities or [],
        "fields": data.get("fields") or list(scraper.FIELD_GROUPS),
        "delay_seconds": scraper.DEFAULT_CONFIG["delay_seconds"] if data.get("delaySeconds") is None else data.get("delaySeconds"),
        "timeout_ms": scraper.DEFAULT_CONFIG["timeout_ms"] if data.get("timeoutMs") is None else data.get("timeoutMs"),
        "headless": True if data.get("headless") is None else bool(data.get("headless")),
    }
    normalized = scraper.normalize_config(config)
    max_cities = data.get("maxCities")
    if max_cities is not None and max_cities != "":
        limit = int(max_cities)
        if limit < 1:
            raise ValueError("maxCities must be >= 1.")
        normalized["cities"] = normalized["cities"][:limit]
        if not normalized["cities"]:
            raise ValueError("maxCities left no cities to scrape.")
    return normalized


def _path_allowed(robots_txt, url):
    if robots_txt is None:
        return True
    return bool(_robots()(robots_txt, url))


def scrape_config(config, session, robots_txt):
    """Scrape normalized config. Skip any URL robots.txt disallows."""
    scraper = _scraper()
    rows = []
    fields = list(config["fields"])
    for entry in config["cities"]:
        rows.append(_scrape_entry(scraper, entry, fields, session, robots_txt))
    return rows


def _scrape_entry(scraper, entry, fields, session, robots_txt):
    city_url = scraper.build_city_url(entry["city"], entry["state"], entry.get("slug"))
    need_crime = "crime" in fields
    crime_url = scraper.build_crime_url(entry["city"], entry["state"], entry.get("slug")) if need_crime else None
    city_allowed = _path_allowed(robots_txt, city_url)
    crime_allowed = True if not need_crime else _path_allowed(robots_txt, crime_url)

    only_crime = need_crime and set(fields) == {"crime"}
    if not city_allowed or (only_crime and not crime_allowed):
        urls = {"city": city_url}
        if crime_url:
            urls["crime"] = crime_url
        return {
            "city": entry["city"],
            "state": entry["state"],
            "urls": urls,
            "ok": False,
            "error": "robots_disallowed",
            "sourceStatus": "robots_disallowed",
            "scrapedAt": iso_now(),
        }

    use_fields = [field for field in fields if field != "crime" or crime_allowed]
    if not use_fields:
        use_fields = ["population"]
    result = scraper.scrape_one(entry, use_fields, session)
    result["scrapedAt"] = iso_now()
    result["sourceStatus"] = "ok" if result.get("ok") else "error"
    if need_crime and not crime_allowed:
        result.setdefault("urls", {})["crime"] = crime_url
        result["crime"] = {"error": "robots_disallowed"}
    return result


def error_item(message):
    return {
        "ok": False,
        "sourceStatus": "error",
        "error": message,
        "scrapedAt": iso_now(),
    }


def summarize(rows):
    blocked = sum(1 for row in rows if row.get("sourceStatus") == "robots_disallowed")
    errors = sum(
        1 for row in rows
        if row.get("sourceStatus") == "error" or (
            row.get("ok") is False and row.get("sourceStatus") != "robots_disallowed"
        )
    )
    return {
        "status": "ok" if errors == 0 and blocked == 0 else "completed_with_errors",
        "pushed": len(rows),
        "blocked": blocked,
        "errors": errors,
    }
