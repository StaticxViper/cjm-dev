#!/usr/bin/env python3
"""
city_data_scraper.py

Fetch city-data.com city and crime pages with Playwright and extract a
curated JSON profile per city with BeautifulSoup.

Run: python city_data_scraper.py
"""
from pathlib import Path
import sys

repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))

import argparse
import json
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

from bs4 import BeautifulSoup, NavigableString
from helper_scripts.utils.logger.logger import setup_logger

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT_PATH = SCRIPT_DIR / "scrape_config.json"
DEFAULT_OUTPUT_PATH = SCRIPT_DIR / "city_data_output.json"
BASE_URL = "https://www.city-data.com"

FIELD_GROUPS = (
    "population",
    "income",
    "housing",
    "cost_of_living",
    "education",
    "crime",
)

STATE_NAMES = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "DC": "District of Columbia",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
}
NAME_TO_ABBR = {name.lower(): abbr for abbr, name in STATE_NAMES.items()}
SMALL_WORDS = {"of", "the", "and"}

DEFAULT_CONFIG = {
    "delay_seconds": 1.5,
    "headless": True,
    "timeout_ms": 30000,
    "cities": [
        {"city": "Cherry Hill", "state": "NJ"},
        {"city": "Cinnaminson", "state": "NJ"},
    ],
    "fields": list(FIELD_GROUPS),
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}
BLOCKED_HOST_FRAGMENTS = (
    "doubleclick",
    "googlesyndication",
    "google-analytics",
    "googletagmanager",
    "adsystem",
    "scorecardresearch",
    "facebook.net",
    "hotjar",
    "ads.",
    "adnxs",
    "rubiconproject",
)
NOT_FOUND_MARKERS = (
    "oops, page not found",
    "<title>page not found",
    "error 404",
)
FETCH_RETRIES = 1

CRIME_HEADER_MAP = {
    "year": "year",
    "murders": "murders",
    "murder": "murders",
    "rapes": "rapes",
    "rape": "rapes",
    "robberies": "robberies",
    "robbery": "robberies",
    "assaults": "assaults",
    "assault": "assaults",
    "burglaries": "burglaries",
    "burglary": "burglaries",
    "auto thefts": "auto_thefts",
    "auto theft": "auto_thefts",
    "motor vehicle thefts": "auto_thefts",
    "motor vehicle theft": "auto_thefts",
    "thefts": "thefts",
    "theft": "thefts",
    "arson": "arson",
    "city-data.com crime index": "crime_index",
    "crime index": "crime_index",
}

logger = setup_logger(
    name="city-data-scraper",
    console_levels=["INFO", "ERROR", "CRITICAL"],
)


def _omit_empty(data):
    if not isinstance(data, dict):
        return data
    return {key: value for key, value in data.items() if value not in (None, "", [], {})}


def parse_int(text):
    if text is None:
        return None
    match = re.search(r"-?[\d,]+", str(text))
    if not match:
        return None
    try:
        return int(match.group(0).replace(",", ""))
    except ValueError:
        return None


def parse_float(text):
    if text is None:
        return None
    match = re.search(r"-?[\d,]+\.?\d*", str(text))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def parse_percent(text):
    if text is None:
        return None
    match = re.search(r"(-?[\d,]+\.?\d*)\s*%", str(text))
    if not match:
        return parse_float(text)
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _as_number(value):
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def parse_money(text):
    if text is None:
        return None
    match = re.search(r"\$[\d,]+(?:\.\d+)?", str(text))
    if match:
        try:
            return _as_number(float(match.group(0).replace("$", "").replace(",", "")))
        except ValueError:
            return None
    return _as_number(parse_float(text))


def _coerce_number(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value) if isinstance(value, float) and value.is_integer() else value
    text = str(value).strip()
    if not text or text in {".", "-", "n/a", "N/A"}:
        return None
    if "%" in text:
        return parse_percent(text)
    if "." in text:
        return parse_float(text)
    return parse_int(text)


def slugify_name(name):
    """Turn a place or state name into a city-data URL token."""
    cleaned = re.sub(r"[^\w\s-]", "", str(name).strip(), flags=re.UNICODE)
    parts = [part for part in re.split(r"[\s]+", cleaned) if part]
    slugged = []
    for index, part in enumerate(parts):
        if "-" in part:
            slugged.append("-".join(
                token if index > 0 and token.lower() in SMALL_WORDS
                else (token[0].upper() + token[1:] if token else token)
                for token in part.split("-")
            ))
            continue
        if index > 0 and part.lower() in SMALL_WORDS:
            slugged.append(part.lower())
        else:
            slugged.append(part[0].upper() + part[1:] if part else part)
    return "-".join(slugged)


def normalize_state(state):
    """Return (abbr, full_name) for a USPS code or full state name."""
    text = str(state or "").strip()
    if not text:
        raise ValueError("state is required.")
    upper = text.upper()
    if upper in STATE_NAMES:
        return upper, STATE_NAMES[upper]
    mapped = NAME_TO_ABBR.get(text.lower())
    if mapped:
        return mapped, STATE_NAMES[mapped]
    raise ValueError(f"Unknown state: {state}")


def city_slug(city, state, slug=None):
    """Build the city-data path token, e.g. Cherry-Hill-New-Jersey."""
    if slug:
        return str(slug).strip().strip("/")
    _abbr, state_name = normalize_state(state)
    return f"{slugify_name(city)}-{slugify_name(state_name)}"


def build_city_url(city, state, slug=None):
    return f"{BASE_URL}/city/{city_slug(city, state, slug)}.html"


def build_crime_url(city, state, slug=None):
    return f"{BASE_URL}/crime/crime-{city_slug(city, state, slug)}.html"


def parse_city_arg(text):
    """Parse 'Cherry Hill,NJ' or 'Chicago, Illinois' into a city dict."""
    raw = str(text).strip()
    if "," not in raw:
        raise ValueError(f"City argument must be 'City,ST': {text}")
    city, state = raw.rsplit(",", 1)
    city = city.strip()
    state = state.strip()
    if not city or not state:
        raise ValueError(f"City argument must be 'City,ST': {text}")
    return {"city": city, "state": state}


def normalize_city_entry(entry):
    if isinstance(entry, str):
        entry = parse_city_arg(entry)
    if not isinstance(entry, dict):
        raise ValueError("Each city must be an object with city and state.")
    city = str(entry.get("city") or "").strip()
    state = str(entry.get("state") or "").strip()
    if not city or not state:
        raise ValueError("Each city requires non-empty city and state.")
    abbr, _name = normalize_state(state)
    out = {"city": city, "state": abbr}
    slug = str(entry.get("slug") or "").strip()
    if slug:
        out["slug"] = slug
    return out


def normalize_config(data):
    """Validate scraper config and fill defaults."""
    if not isinstance(data, dict):
        raise ValueError("Config must be a JSON object.")

    out = dict(DEFAULT_CONFIG)
    out.update(data)

    cities = out.get("cities")
    if isinstance(cities, dict):
        cities = [cities]
    if isinstance(cities, str):
        cities = [cities]
    if not isinstance(cities, list) or not cities:
        raise ValueError("cities is required and must be a non-empty list.")
    out["cities"] = [normalize_city_entry(item) for item in cities]

    fields = out.get("fields", list(FIELD_GROUPS))
    if isinstance(fields, str):
        fields = [fields]
    if not isinstance(fields, list) or not fields:
        raise ValueError("fields must be a non-empty list.")
    cleaned_fields = []
    for field in fields:
        name = str(field).strip()
        if name not in FIELD_GROUPS:
            raise ValueError(f"Unknown field group: {field}")
        if name not in cleaned_fields:
            cleaned_fields.append(name)
    out["fields"] = cleaned_fields

    try:
        out["delay_seconds"] = float(out.get("delay_seconds", 1.5))
    except (TypeError, ValueError) as exc:
        raise ValueError("delay_seconds must be a number.") from exc
    if out["delay_seconds"] < 0:
        raise ValueError("delay_seconds must be >= 0.")

    try:
        out["timeout_ms"] = int(out.get("timeout_ms", 30000))
    except (TypeError, ValueError) as exc:
        raise ValueError("timeout_ms must be an integer.") from exc
    if out["timeout_ms"] <= 0:
        raise ValueError("timeout_ms must be > 0.")

    out["headless"] = bool(out.get("headless", True))
    return out


def load_config(path):
    path = Path(path)
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return normalize_config(data)


def save_output(payload, json_path):
    """Write output atomically so a failed run cannot truncate the file."""
    path = Path(json_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    os.replace(tmp_path, path)
    logger.critical("Saved %d city profile(s) to %s", len(payload.get("results") or []), path)


def resolve_config(args):
    input_path = Path(args.input) if args.input else DEFAULT_INPUT_PATH
    if input_path.is_file():
        base = load_config(input_path)
        logger.info("Loaded scrape config from %s", input_path)
    else:
        if args.input:
            raise FileNotFoundError(f"Config file not found: {input_path}")
        logger.info("No scrape config file found; using built-in defaults.")
        base = normalize_config(dict(DEFAULT_CONFIG))

    if args.cities:
        base["cities"] = [normalize_city_entry(item) for item in args.cities]
    if args.fields:
        base["fields"] = args.fields
    if args.delay is not None:
        base["delay_seconds"] = args.delay
    if args.timeout_ms is not None:
        base["timeout_ms"] = args.timeout_ms
    if args.headless is not None:
        base["headless"] = args.headless
    return normalize_config(base)


def _visible_text(soup):
    return soup.get_text(" ", strip=True) if soup is not None else ""


def _bold_following_text(tag):
    parts = []
    sibling = tag.next_sibling
    while sibling is not None:
        name = getattr(sibling, "name", None)
        if name in {"b", "br", "h1", "h2", "h3", "h4", "table", "ul", "section"}:
            break
        if isinstance(sibling, NavigableString):
            text = str(sibling).strip()
            if text:
                parts.append(text)
        elif name is None:
            text = str(sibling).strip()
            if text:
                parts.append(text)
        else:
            break
        sibling = sibling.next_sibling
    return " ".join(parts).strip()


def _value_for_label(soup, pattern):
    regex = re.compile(pattern, re.I)
    for tag in soup.find_all("b"):
        label = tag.get_text(" ", strip=True)
        match = regex.search(label)
        if not match:
            continue
        remainder = label[match.end():].strip(" :")
        if remainder:
            return remainder
        following = _bold_following_text(tag)
        if following:
            return following
    return None


def _search(text, pattern):
    if not text:
        return None
    return re.search(pattern, text, re.I)


def parse_population(soup):
    section = soup.find(id="city-population") or soup
    text = _visible_text(section)
    page_text = text if section is not soup else _visible_text(soup)
    data = {}

    pop = _search(page_text, r"Population in (\d{4}):\s*([\d,]+)")
    if pop:
        data["year"] = int(pop.group(1))
        data["total"] = parse_int(pop.group(2))

    urban = _search(page_text, r"([\d.]+)%\s*urban")
    rural = _search(page_text, r"([\d.]+)%\s*rural")
    if urban:
        data["urban_pct"] = float(urban.group(1))
    if rural:
        data["rural_pct"] = float(rural.group(1))

    change = _search(page_text, r"Population change since 2000:\s*([+\-]?[\d.]+)\s*%")
    if change:
        data["change_since_2000_pct"] = float(change.group(1))

    age_text = _value_for_label(soup, r"Median resident age") or ""
    if not age_text:
        age_match = _search(_visible_text(soup), r"Median resident age:\s*([\d.]+)")
        if age_match:
            data["median_age"] = float(age_match.group(1))
    else:
        age = parse_float(age_text)
        if age is not None:
            data["median_age"] = age

    sex_section = soup.find(id="population-by-sex") or soup
    sex_text = _visible_text(sex_section)
    males = _search(sex_text, r"Males:\s*([\d,]+)")
    females = _search(sex_text, r"Females:\s*([\d,]+)")
    if males:
        data["males"] = parse_int(males.group(1))
    if females:
        data["females"] = parse_int(females.group(1))
    return _omit_empty(data)


def parse_income(soup):
    text = _visible_text(soup)
    data = {}
    year_match = _search(text, r"Estimated median household income in (\d{4})")
    if year_match:
        data["year"] = int(year_match.group(1))

    household = _value_for_label(soup, r"Estimated median household income in \d{4}")
    if not household:
        match = _search(text, r"Estimated median household income in \d{4}:\s*(\$[\d,]+)")
        household = match.group(1) if match else None
    money = parse_money(household)
    if money is not None:
        data["median_household"] = money

    per_capita = _value_for_label(soup, r"Estimated per capita income in \d{4}")
    if not per_capita:
        match = _search(text, r"Estimated per capita income in \d{4}:\s*(\$[\d,]+)")
        per_capita = match.group(1) if match else None
    per_capita_money = parse_money(per_capita)
    if per_capita_money is not None:
        data["per_capita"] = per_capita_money

    poverty = _value_for_label(soup, r"Percentage of residents living in poverty in \d{4}")
    if not poverty:
        match = _search(text, r"Percentage of residents living in poverty in \d{4}:\s*([\d.]+)\s*%")
        poverty = match.group(0) if match else None
    rate = parse_percent(poverty) if poverty else None
    if rate is None and poverty:
        rate = parse_float(poverty)
    if rate is not None:
        data["poverty_rate"] = rate
    return _omit_empty(data)


def parse_housing(soup):
    text = _visible_text(soup)
    data = {}
    value = _value_for_label(soup, r"Estimated median house or condo value in \d{4}")
    if not value:
        match = _search(text, r"Estimated median house or condo value in \d{4}:\s*(\$[\d,]+)")
        value = match.group(1) if match else None
    money = parse_money(value)
    if money is not None:
        data["median_home_value"] = money

    rent = _value_for_label(soup, r"Median gross rent in \d{4}")
    if not rent:
        match = _search(text, r"Median gross rent in \d{4}:\s*(\$[\d,]+)")
        rent = match.group(1) if match else None
    rent_money = parse_money(rent)
    if rent_money is not None:
        data["median_gross_rent"] = rent_money

    renter = _search(text, r"% of renters here:\s*([\d.]+)\s*%")
    if not renter:
        renter = _search(text, r"Renter-occupied apartments:.*?([\d.]+)\s*%")
    if not renter:
        renter = _search(text, r"Renter occupied housing units\s*\(?%?\)?:?\s*([\d.]+)\s*%")
    if renter:
        data["renter_pct"] = float(renter.group(1))
    return _omit_empty(data)


def parse_cost_of_living(soup):
    text = _visible_text(soup)
    labeled = _value_for_label(soup, r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\s+cost of living index")
    match = _search(
        text,
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\s+cost of living index(?:\s+in [^:]+)?:\s*([\d.]+)",
    )
    data = {}
    if match:
        data["year"] = int(match.group(2))
        data["index"] = float(match.group(3))
    elif labeled:
        index = parse_float(labeled)
        if index is not None:
            data["index"] = index
        year = _search(text, r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\s+cost of living index")
        if year:
            data["year"] = int(year.group(2))
    return _omit_empty(data)


def parse_education(soup):
    data = {}
    heading = None
    for tag in soup.find_all(["h2", "h3", "h4", "b"]):
        if re.search(r"For population 25 years and over", tag.get_text(" ", strip=True), re.I):
            heading = tag
            break
    block_text = ""
    if heading is not None:
        parts = [heading.get_text(" ", strip=True)]
        sibling = heading.next_sibling
        hops = 0
        while sibling is not None and hops < 12:
            name = getattr(sibling, "name", None)
            if name in {"h2", "h3", "h4"}:
                break
            if isinstance(sibling, NavigableString):
                text = str(sibling).strip()
                if text:
                    parts.append(text)
            elif name:
                parts.append(sibling.get_text(" ", strip=True))
            sibling = sibling.next_sibling
            hops += 1
        block_text = " ".join(parts)
    if not block_text:
        block_text = _visible_text(soup)

    hs = _search(block_text, r"High school or higher:\s*([\d.]+)\s*%")
    bach = _search(block_text, r"Bachelor'?s degree or higher:\s*([\d.]+)\s*%")
    if hs:
        data["hs_or_higher_pct"] = float(hs.group(1))
    if bach:
        data["bachelors_or_higher_pct"] = float(bach.group(1))
    return _omit_empty(data)


def _normalize_header(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _map_crime_header(text):
    normalized = _normalize_header(text)
    if normalized in CRIME_HEADER_MAP:
        return CRIME_HEADER_MAP[normalized]
    for key, mapped in sorted(CRIME_HEADER_MAP.items(), key=lambda item: len(item[0]), reverse=True):
        if key in normalized:
            return mapped
    return None


def _table_candidates(soup):
    seen = []
    tab = soup.find(id="crimeTab")
    if tab is not None:
        seen.append(tab)
    for table in soup.find_all("table"):
        if table is tab:
            continue
        seen.append(table)
    return seen


def _row_cells(row):
    return [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]


def _parse_year_row_table(table):
    all_rows = table.find_all("tr")
    header_idx = None
    headers = []
    for idx, row in enumerate(all_rows):
        mapped = [_map_crime_header(cell) for cell in _row_cells(row)]
        if "year" in mapped and "murders" in mapped:
            header_idx = idx
            headers = mapped
            break
    if header_idx is None:
        return []
    rows = []
    for row in all_rows[header_idx + 1:]:
        values = _row_cells(row)
        if len(values) < 2:
            continue
        item = {}
        for index, key in enumerate(headers):
            if not key or index >= len(values):
                continue
            number = _coerce_number(values[index])
            if number is not None:
                item[key] = number
        if "year" in item:
            rows.append(item)
    return rows


def _year_cells(cells):
    years = []
    for cell in cells[1:]:
        year = parse_int(cell)
        if year and 1900 <= year <= 2100:
            years.append(year)
        else:
            years.append(None)
    return years


def _parse_year_column_table(table):
    all_rows = table.find_all("tr")
    header_idx = None
    years = []
    for idx, row in enumerate(all_rows):
        cells = _row_cells(row)
        if len(cells) < 3:
            continue
        candidate = _year_cells(cells)
        if sum(1 for year in candidate if year) >= 2:
            header_idx = idx
            years = candidate
            break
    if header_idx is None:
        return []

    by_year = {year: {"year": year} for year in years if year}
    mapped_rows = 0
    for row in all_rows[header_idx + 1:]:
        values = _row_cells(row)
        if len(values) < 2:
            continue
        key = _map_crime_header(values[0])
        if not key or key == "year":
            continue
        mapped_rows += 1
        for year, raw in zip(years, values[1:]):
            if year is None:
                continue
            number = _coerce_number(raw.split("(")[0] if "(" in raw else raw)
            if number is not None:
                by_year[year][key] = number
    if mapped_rows < 2:
        return []
    return [item for item in by_year.values() if len(item) > 1]


def parse_crime_table(soup):
    rows = []
    for table in _table_candidates(soup):
        rows = _parse_year_row_table(table) or _parse_year_column_table(table)
        if rows:
            break
    rows.sort(key=lambda item: item.get("year") or 0, reverse=True)
    return rows


def parse_crime_html(html):
    if not html:
        return {}
    soup = BeautifulSoup(html, "html.parser")
    text = _visible_text(soup)
    data = {}

    index_match = _search(
        text,
        r"The (\d{4}) crime rate in .+? is ([\d.]+)\s*\(City-Data\.com crime index\)",
    )
    if index_match:
        data["index_year"] = int(index_match.group(1))
        data["index"] = float(index_match.group(2))

    vs_match = _search(text, r"([\d.]+) times (higher|lower) than the U\.S\. average")
    if vs_match:
        data["vs_us_average"] = f"{vs_match.group(1)} times {vs_match.group(2)}"

    yoy = _search(text, r"crime rate (fell|rose|increased|decreased) by ([\d.]+)\s*%")
    if yoy:
        change = float(yoy.group(2))
        if yoy.group(1).lower() in {"fell", "decreased"}:
            change = -change
        data["yoy_change_pct"] = change

    homicides = _search(text, r"number of homicides stood at ([\d,]+)")
    if homicides:
        data["homicides"] = parse_int(homicides.group(1))

    violent = _search(text, r"Violent crime rate in (\d{4})\s+\S+:\s*([\d.]+)")
    if not violent:
        violent = _search(text, r"Violent crime rate in (\d{4}).{0,120}?([\d.]+)")
    if violent:
        data["violent_crime_rate"] = float(violent.group(2))
        data.setdefault("index_year", int(violent.group(1)))

    prop = _search(text, r"Property crime rate in (\d{4})\s+\S+:\s*([\d.]+)")
    if not prop:
        prop = _search(text, r"Property crime rate in (\d{4}).{0,120}?([\d.]+)")
    if prop:
        data["property_crime_rate"] = float(prop.group(2))

    officers = _value_for_label(soup, r"Officers per 1,000 residents here")
    if not officers:
        officer_match = _search(text, r"Officers per 1,000 residents here:\s*([\d.]+)")
        officers = officer_match.group(1) if officer_match else None
    officer_rate = parse_float(officers)
    if officer_rate is not None:
        data["officers_per_1000"] = officer_rate

    by_year = parse_crime_table(soup)
    if by_year:
        data["by_year"] = by_year
        latest = by_year[0]
        data.setdefault("index", latest.get("crime_index"))
        data.setdefault("index_year", latest.get("year"))
        if data.get("homicides") is None and latest.get("murders") is not None:
            data["homicides"] = latest["murders"]
    return _omit_empty(data)


CITY_PARSERS = {
    "population": parse_population,
    "income": parse_income,
    "housing": parse_housing,
    "cost_of_living": parse_cost_of_living,
    "education": parse_education,
}


def parse_city_html(html, fields):
    if not html:
        return {}
    soup = BeautifulSoup(html, "html.parser")
    parsed = {}
    for field in fields:
        parser = CITY_PARSERS.get(field)
        if parser is None:
            continue
        values = parser(soup)
        if values:
            parsed[field] = values
    return parsed


def merge_crime(primary, fallback):
    if not fallback:
        return primary or {}
    if not primary:
        return fallback
    merged = dict(fallback)
    merged.update({key: value for key, value in primary.items() if key != "by_year"})
    if primary.get("by_year"):
        merged["by_year"] = primary["by_year"]
    elif fallback.get("by_year"):
        merged["by_year"] = fallback["by_year"]
    return _omit_empty(merged)


def is_not_found(html, status=None):
    if status == 404:
        return True
    if not html:
        return False
    lowered = html.lower()
    return any(marker in lowered for marker in NOT_FOUND_MARKERS)


def _host_blocked(url):
    host = urlparse(url).netloc.lower()
    return any(fragment in host or fragment in url.lower() for fragment in BLOCKED_HOST_FRAGMENTS)


def _should_block_request(request):
    if request.resource_type in BLOCKED_RESOURCE_TYPES:
        return True
    return _host_blocked(request.url)


class CityDataSession:
    """One Playwright browser reused for the whole scrape run."""

    def __init__(self, headless=True, timeout_ms=30000, delay_seconds=1.5):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.delay_seconds = delay_seconds
        self._playwright = None
        self._browser = None
        self._page = None
        self._requests_done = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def close(self):
        page, browser, playwright = self._page, self._browser, self._playwright
        self._page = None
        self._browser = None
        self._playwright = None
        for closer, label in (
            (getattr(page, "close", None), "page"),
            (getattr(browser, "close", None), "browser"),
            (getattr(playwright, "stop", None), "playwright"),
        ):
            if closer is None:
                continue
            try:
                closer()
            except Exception as exc:
                logger.error("Failed to close %s: %s", label, exc)

    def _ensure_browser(self):
        if self._page is not None:
            return self._page
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            raise RuntimeError(f"Playwright is not available: {exc}") from exc
        try:
            if self._playwright is None:
                self._playwright = sync_playwright().start()
            if self._browser is None:
                self._browser = self._playwright.chromium.launch(headless=self.headless)
            self._page = self._browser.new_page(
                user_agent=USER_AGENT,
                viewport={"width": 1280, "height": 720},
            )
            self._page.set_default_timeout(self.timeout_ms)
            self._page.route("**/*", self._on_route)
            return self._page
        except Exception:
            self.close()
            raise

    def _on_route(self, route):
        if _should_block_request(route.request):
            route.abort()
            return
        route.continue_()

    def _sleep_between_requests(self):
        if self._requests_done <= 0 or self.delay_seconds <= 0:
            return
        time.sleep(self.delay_seconds)

    def fetch(self, url, wait_for=None):
        """Return (status_code, html, error)."""
        page = self._ensure_browser()
        last_error = None
        for attempt in range(FETCH_RETRIES + 1):
            self._sleep_between_requests()
            try:
                response = page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=self.timeout_ms,
                )
                if wait_for:
                    try:
                        page.wait_for_selector(wait_for, timeout=min(8000, self.timeout_ms))
                    except Exception:
                        pass
                html = page.content() or ""
                status = response.status if response is not None else 0
                self._requests_done += 1
                if is_not_found(html, status):
                    return 404, html, "HTTP 404"
                return status or 200, html, None
            except Exception as exc:
                last_error = exc
                self._requests_done += 1
                logger.info("Fetch attempt %d failed for %s: %s", attempt + 1, url, exc)
                if attempt < FETCH_RETRIES:
                    continue
        return 0, "", str(last_error)


def scrape_one(city_entry, fields, session):
    city = city_entry["city"]
    state = city_entry["state"]
    slug = city_entry.get("slug")
    city_url = build_city_url(city, state, slug)
    result = {
        "city": city,
        "state": state,
        "urls": {"city": city_url},
        "ok": True,
    }
    need_crime = "crime" in fields
    if need_crime:
        result["urls"]["crime"] = build_crime_url(city, state, slug)

    logger.info("Fetching city page: %s", city_url)
    status, city_html, error = session.fetch(
        city_url,
        wait_for="#crimeTab" if need_crime else None,
    )
    if error and status == 404:
        result["ok"] = False
        result["error"] = "City page not found"
    elif error or status >= 400:
        result["ok"] = False
        result["error"] = error or f"HTTP {status}"
    else:
        result.update(parse_city_html(city_html, fields))

    if not need_crime:
        return result

    crime_url = result["urls"]["crime"]
    logger.info("Fetching crime page: %s", crime_url)
    crime_status, crime_html, crime_error = session.fetch(crime_url, wait_for="#crimeTab")
    crime_data = {}
    if crime_error and crime_status == 404:
        fallback = parse_crime_html(city_html) if city_html else {}
        if fallback:
            crime_data = fallback
        else:
            crime_data = {"error": "Crime page not found"}
    elif crime_error or crime_status >= 400:
        fallback = parse_crime_html(city_html) if city_html else {}
        crime_data = merge_crime({}, fallback)
        if not crime_data:
            crime_data = {"error": crime_error or f"HTTP {crime_status}"}
    else:
        crime_data = merge_crime(parse_crime_html(crime_html), parse_crime_html(city_html))

    if crime_data:
        result["crime"] = crime_data
    return result


def scrape_cities(config, output_path, session=None):
    config = normalize_config(config)
    own_session = session is None
    if session is None:
        session = CityDataSession(
            headless=config["headless"],
            timeout_ms=config["timeout_ms"],
            delay_seconds=config["delay_seconds"],
        )
    results = []
    try:
        logger.critical("Scraping %d city-data profile(s)", len(config["cities"]))
        for city_entry in config["cities"]:
            try:
                results.append(scrape_one(city_entry, config["fields"], session))
            except Exception as exc:
                logger.error("Failed %s, %s: %s", city_entry.get("city"), city_entry.get("state"), exc)
                results.append({
                    "city": city_entry.get("city"),
                    "state": city_entry.get("state"),
                    "urls": {
                        "city": build_city_url(city_entry["city"], city_entry["state"], city_entry.get("slug")),
                    },
                    "ok": False,
                    "error": str(exc),
                })
        payload = {
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "results": results,
        }
        save_output(payload, output_path)
        return payload
    finally:
        if own_session:
            session.close()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Scrape city-data.com city and crime pages into JSON",
    )
    parser.add_argument(
        "--input",
        default=str(DEFAULT_INPUT_PATH),
        help=f"Scrape config JSON (default {DEFAULT_INPUT_PATH.name})",
    )
    parser.add_argument(
        "--output-path",
        default=str(DEFAULT_OUTPUT_PATH),
        help=f"Where to write profiles (default {DEFAULT_OUTPUT_PATH.name})",
    )
    parser.add_argument(
        "--cities",
        nargs="+",
        help='Cities as "City,ST" (overrides --input cities)',
    )
    parser.add_argument(
        "--fields",
        nargs="+",
        choices=FIELD_GROUPS,
        help="Field groups to extract (overrides --input fields)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        help="Seconds to wait between HTTP requests",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        help="Playwright navigation timeout in milliseconds",
    )
    headless = parser.add_mutually_exclusive_group()
    headless.add_argument(
        "--headless",
        dest="headless",
        action="store_true",
        help="Run Chromium headless (default)",
    )
    headless.add_argument(
        "--no-headless",
        dest="headless",
        action="store_false",
        help="Show the browser window",
    )
    parser.set_defaults(headless=None)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        config = resolve_config(args)
        scrape_cities(config, args.output_path)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        logger.error("%s", exc)
        return 1
    except Exception as exc:
        logger.error("City-data scrape failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
