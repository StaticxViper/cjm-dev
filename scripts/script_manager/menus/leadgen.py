"""Leadgen menu. Reads JSON data files and returns CLI args. Does not import leadgen.py."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.script_manager import repo_root
from scripts.script_manager.menus.prompts import ask, parse_index_selection, say, yes

_LEAD_DIR_PARTS = ("scripts", "lead_automation")
_DEFAULTS = {
    "min_score": 55,
    "min_reviews": 0,
    "filter_franchises": True,
    "objective": "phone",
    "require_website": False,
    "lead_enrichment": True,
    "output_mode": "json",
    "json_output": "leads_output.json",
    "leadgen_type": "api_manager",
    "playwright_max_pages": 20,
    "playwright_max_results_per_search": 400,
    "playwright_area_expansion": "off",
    "skip_searched": True,
    "search_history_path": "leadgen_search_history.json",
    "discovery_mode": "standard",
    "nb_max_age_days": 365,
    "nb_very_new_days": 90,
    "nb_min_score": 50,
    "nb_website_check": "deep",
    "nb_csv_output": "new_business_leads.csv",
    "nb_max_records_per_source": 200,
    "nb_score_rules_path": "new_business_score_rules.json",
    "nb_regions_file": "geo_regions.json",
    "nb_sources": "",
}
_LEADGEN_TYPES = ("api_manager", "playwright")
_OBJECTIVES = ("phone", "email", "either", "both")
_OUTPUTS = ("json", "dashboard", "both")
_EXPANSIONS = ("off", "light", "dense")
_KEYWORD_GROUP_LABELS = (
    ("home_exterior", "Home exterior"),
    ("home_interior", "Home interior"),
    ("cleaning", "Cleaning / junk"),
    ("auto", "Auto"),
    ("events", "Events / food"),
    ("pets", "Pets"),
    ("personal_care", "Personal care"),
    ("professional", "Professional services"),
    ("education_care", "Education / care"),
    ("other", "Other"),
)
_KEYWORD_GROUPS = {
    "home_exterior": [
        "landscaping", "lawn care", "tree service", "roofing", "fencing", "deck building",
        "garage door", "window installation", "siding", "gutter cleaning", "pressure washing",
        "concrete", "masonry",
    ],
    "home_interior": [
        "plumbing", "hvac", "electrician", "general contractor", "remodeling", "home renovation",
        "painting", "flooring", "carpentry", "handyman", "drywall", "appliance repair",
    ],
    "cleaning": [
        "window cleaning", "carpet cleaning", "house cleaning", "commercial cleaning",
        "junk removal", "upholstery cleaning",
    ],
    "auto": [
        "mobile detailing", "auto detailing", "auto repair", "tire shop", "towing",
        "car window tinting", "mobile mechanic",
    ],
    "events": [
        "photography", "wedding photography", "videography", "dj services", "event planning",
        "catering", "bakery", "florist",
    ],
    "pets": ["pet grooming", "dog walking", "pet sitting", "dog training"],
    "personal_care": [
        "barber", "hair salon", "nail salon", "massage therapy", "personal trainer",
        "fitness studio", "tattoo shop", "med spa", "beauty salon",
    ],
    "professional": [
        "accounting", "bookkeeping", "tax preparation", "real estate agent", "insurance agency",
        "mortgage broker", "financial advisor", "law firm", "attorney", "private investigator",
    ],
    "education_care": [
        "tutoring", "music lessons", "driving school", "childcare", "senior care", "home care",
    ],
    "other": ["moving company", "pest control", "pool service", "pool cleaning", "locksmith"],
}


def configure(script=None, *, reader=input, writer=print, repo: Path | None = None, settings_path: Path | None = None) -> list[str] | None:
    """Leadgen screen. Returns args to queue, or None to go back."""
    del script
    root = repo or repo_root()
    lead_dir = root.joinpath(*_LEAD_DIR_PARTS)
    settings_path = settings_path or (lead_dir / "leadgen_settings.json")
    keywords = _load_json(lead_dir / "keywords.json", {})
    coords = _load_json(lead_dir / "coords.json", {})
    niches = _load_json(lead_dir / "niches.json", {})
    while True:
        settings = _load_settings(settings_path)
        say(writer, "")
        say(writer, "=== Lead Generation ===")
        say(
            writer,
            f"  Current: {settings['leadgen_type']} | objective={settings['objective']} | "
            f"min score {settings['min_score']} | output {settings['output_mode']}",
        )
        say(writer, "1) Run (type a niche and location)")
        say(writer, "2) Settings (save defaults, do not run)")
        say(writer, "3) High-volume preset (Playwright, area expansion, no Facebook enrich)")
        say(writer, "4) Back")
        say(writer, "5) Lead Search (micro-niche intent search)")
        say(writer, "6) New-business discovery")
        say(writer, "7) Review niche results")
        choice = ask(reader, "Select [1]: ") or "1"
        if choice == "4":
            return None
        if choice == "2":
            updated = _edit_settings(settings, reader, writer)
            _save_settings(updated, settings_path, writer)
            continue
        if choice == "7":
            _review_results(lead_dir / "niche_leads_output.json", reader, writer)
            continue
        if choice == "3":
            preset = _high_volume(settings)
            _save_settings(preset, settings_path, writer)
            say(writer, "Applied high-volume Playwright preset.")
            if not yes(ask(reader, "Type a niche and location and add to the queue? [Y/n]: "), True):
                continue
            return _standard_run(preset, keywords, coords, reader, writer)
        if choice == "5":
            queued = _niche_run(settings, niches, coords, reader, writer)
            if queued is not None:
                return queued
            continue
        if choice == "6":
            queued = _new_business_run(settings, coords, reader, writer)
            if queued is not None:
                return queued
            continue
        if choice == "1":
            queued = _standard_run(settings, keywords, coords, reader, writer)
            if queued is not None:
                return queued
            continue
        say(writer, "Invalid choice. Please select 1, 2, 3, 4, 5, 6, or 7.")


def _standard_run(settings, keywords, coords, reader, writer) -> list[str] | None:
    from scripts.lead_automation.search_input import (
        EMPTY_NICHE_MESSAGE,
        EmptySearchInput,
        is_presets_choice,
        parse_term_list,
        require_niches,
    )

    say(writer, "")
    say(writer, "Business niche(s), comma-separated. Example: mobile dog grooming")
    say(writer, "Type presets to choose from keywords.json instead.")
    raw_niche = ask(reader, "Business niche(s): ")
    if is_presets_choice(raw_niche):
        if not keywords:
            say(writer, "keywords.json has no presets.")
            say(writer, EMPTY_NICHE_MESSAGE)
            return None
        chosen_keywords = _prompt_keywords(keywords, reader, writer)
        locations = _prompt_locations(coords, reader, writer)
        say(writer, f"Selected {len(chosen_keywords)} keyword(s) and {len(locations)} location(s).")
        if not yes(ask(reader, "Add this run to the queue? [Y/n]: "), True):
            return None
        return _settings_args(settings) + ["--mode", "standard"] + _scope_args(keywords, chosen_keywords, locations, coords)
    try:
        niches = require_niches(raw_niche)
    except EmptySearchInput as exc:
        say(writer, str(exc))
        return None
    say(writer, "Keyword search string(s), comma-separated.")
    say(writer, "Leave blank to search each niche in the locations you pick.")
    say(writer, "Example: pressure washing near Cherry Hill NJ")
    raw_keywords = ask(reader, "Keyword search string(s): ")
    typed_keywords = parse_term_list(raw_keywords)
    locations = _prompt_locations(coords, reader, writer)
    if not locations:
        say(writer, "Select at least one location.")
        return None
    say(writer, f"Niches: {', '.join(niches)}")
    if typed_keywords:
        say(writer, f"Keywords: {', '.join(typed_keywords)}")
    else:
        say(writer, "Keywords: built from the niche and the selected location(s).")
    say(writer, f"Locations: {len(locations)}")
    if not yes(ask(reader, "Add this run to the queue? [Y/n]: "), True):
        return None
    args = _settings_args(settings, include_json_path=False)
    args.extend(["--mode", "standard", "--free-text"])
    args.extend(["--niche", ", ".join(niches)])
    if typed_keywords:
        args.extend(["--keywords", *typed_keywords])
    all_locations = _locations(coords)
    if len(locations) != len(all_locations):
        args.extend(_location_flags(locations))
    return args


def _niche_run(settings, niches, coords, reader, writer) -> list[str] | None:
    catalog = _niche_list(niches)
    if not catalog:
        say(writer, "No niches found in niches.json.")
        return None
    say(writer, "")
    say(writer, "=== Lead Search ===")
    for index, niche in enumerate(catalog, start=1):
        say(writer, f" {index:>2}) {niche.get('display_name') or niche.get('id')}")
    raw = ask(reader, "Niche number: ")
    try:
        niche = catalog[int(raw) - 1]
    except (ValueError, IndexError):
        say(writer, "Invalid niche.")
        return None
    locations = _prompt_locations(coords, reader, writer)
    min_reviews = _prompt_int(reader, "Minimum reviews", niche.get("suggested_min_reviews") or settings["min_reviews"])
    min_rating = ask(reader, f"Minimum rating [{niche.get('suggested_min_rating') or 4.5}]: ")
    min_score = _prompt_int(reader, "Minimum score", settings["min_score"])
    radius = _prompt_int(reader, "Radius (meters)", 50000)
    max_leads = _prompt_int(reader, "Number of leads (0 = all)", 0)
    exclude_franchises = yes(ask(reader, "Exclude franchises? [Y/n]: "), True)
    weak_site = yes(ask(reader, "Prioritize no/weak website? [Y/n]: "), True)
    require_active = yes(ask(reader, "Require active business? [Y/n]: "), True)
    extra_raw = ask(reader, "Extra keywords (comma-separated) []: ")
    if not yes(ask(reader, "Add this niche search to the queue? [Y/n]: "), True):
        return None
    args = ["--niche", str(niche.get("id") or niche.get("display_name"))]
    args.extend(_location_flags(locations))
    args.extend(["--min-reviews", str(min_reviews), "--min-score", str(min_score)])
    args.extend(["--radius", str(radius), "--max-leads", str(max_leads)])
    if min_rating:
        args.extend(["--min-rating", min_rating])
    args.append("--filter-franchises" if exclude_franchises else "--no-filter-franchises")
    if weak_site:
        args.append("--exclude-strong-websites")
    if require_active:
        args.append("--require-active-business")
    extra = [part.strip() for part in extra_raw.split(",") if part.strip()]
    if extra:
        args.extend(["--extra-keywords", *extra])
    args.extend(["--json-path", "niche_leads_output.json"])
    return args


def _new_business_run(settings, coords, reader, writer) -> list[str] | None:
    say(writer, "")
    say(writer, "New-business discovery")
    say(writer, "Searches public registration and license sources for newly formed businesses.")
    locations = _prompt_locations(coords, reader, writer)
    max_age = _prompt_int(reader, "Max age in days", settings["nb_max_age_days"])
    min_score = _prompt_int(reader, "Minimum new-business score", settings["nb_min_score"])
    if not yes(ask(reader, "Add new-business discovery to the queue? [Y/n]: "), True):
        return None
    args = ["--mode", "new-business", "--max-age-days", str(max_age), "--min-new-business-score", str(min_score)]
    args.extend(_location_flags(locations))
    args.extend(["--json-path", "new_business_leads.json"])
    return args


def _edit_settings(settings: dict, reader, writer) -> dict:
    current = dict(settings)
    fields = (
        ("1", "Leadgen type", "leadgen_type"),
        ("2", "Playwright max pages", "playwright_max_pages"),
        ("3", "Max results per search", "playwright_max_results_per_search"),
        ("4", "Area expansion", "playwright_area_expansion"),
        ("5", "Skip already searched", "skip_searched"),
        ("6", "Search history path", "search_history_path"),
        ("7", "Minimum score", "min_score"),
        ("8", "Minimum reviews", "min_reviews"),
        ("9", "Filter franchises", "filter_franchises"),
        ("10", "Objective", "objective"),
        ("11", "Require website", "require_website"),
        ("12", "Lead enrichment", "lead_enrichment"),
        ("13", "Output", "output_mode"),
        ("14", "JSON output path", "json_output"),
    )
    while True:
        say(writer, "")
        say(writer, "--- Settings (enter a number to change, Enter to save) ---")
        for number, label, key in fields:
            say(writer, f" {number:>2}) {label:<28} [{current[key]}]")
        raw = ask(reader, "Change setting [Enter=save & return]: ")
        if not raw:
            return current
        match = {number: key for number, _label, key in fields}
        key = match.get(raw)
        if key is None:
            say(writer, "Enter a setting number from the list, or press Enter to save.")
            continue
        current[key] = _edit_value(key, current[key], reader, writer)


def _edit_value(key, value, reader, writer):
    if key == "leadgen_type":
        return _choose_value(reader, writer, "Leadgen type", _LEADGEN_TYPES, str(value))
    if key == "objective":
        return _choose_value(reader, writer, "Objective", _OBJECTIVES, str(value))
    if key == "output_mode":
        return _choose_value(reader, writer, "Output", _OUTPUTS, str(value))
    if key == "playwright_area_expansion":
        return _choose_value(reader, writer, "Area expansion", _EXPANSIONS, str(value))
    if key in {"skip_searched", "filter_franchises", "require_website", "lead_enrichment"}:
        return yes(ask(reader, f"{key.replace('_', ' ')}? [Y/n]: "), bool(value))
    if key in {"playwright_max_pages", "playwright_max_results_per_search", "min_score", "min_reviews"}:
        return _prompt_int(reader, key.replace("_", " "), value)
    raw = ask(reader, f"{key.replace('_', ' ')} [{value}]: ")
    return raw or value


def _choose_value(reader, writer, title, options, default):
    say(writer, title)
    for index, option in enumerate(options, start=1):
        say(writer, f"{index}) {option}")
    default_index = options.index(default) + 1 if default in options else 1
    raw = ask(reader, f"Select [{default_index}]: ")
    if not raw:
        return options[default_index - 1]
    if raw.isdigit() and 1 <= int(raw) <= len(options):
        return options[int(raw) - 1]
    if raw in options:
        return raw
    say(writer, "That choice is not in the list. Keeping the current value.")
    return default


def _high_volume(settings: dict) -> dict:
    updated = dict(settings)
    updated["leadgen_type"] = "playwright"
    updated["playwright_max_pages"] = max(20, int(updated["playwright_max_pages"] or 20))
    updated["playwright_max_results_per_search"] = max(400, int(updated["playwright_max_results_per_search"] or 400))
    updated["playwright_area_expansion"] = "light"
    updated["skip_searched"] = True
    updated["min_score"] = min(int(updated["min_score"]), 55)
    updated["min_reviews"] = 0
    updated["filter_franchises"] = True
    updated["objective"] = "phone"
    updated["require_website"] = False
    updated["lead_enrichment"] = False
    if updated["output_mode"] not in ("json", "dashboard", "both"):
        updated["output_mode"] = "json"
    return updated


def _settings_args(settings: dict, include_json_path: bool = True) -> list[str]:
    args = [
        "--defaults",
        "--leadgen-type", str(settings["leadgen_type"]),
        "--playwright-max-pages", str(settings["playwright_max_pages"]),
        "--playwright-max-results-per-search", str(settings["playwright_max_results_per_search"]),
        "--playwright-area-expansion", str(settings["playwright_area_expansion"]),
        "--search-history-path", str(settings["search_history_path"]),
        "--min-score", str(settings["min_score"]),
        "--min-reviews", str(settings["min_reviews"]),
        "--objective", str(settings["objective"]),
        "--output", str(settings["output_mode"]),
    ]
    if include_json_path:
        args.extend(["--json-path", str(settings["json_output"])])
    args.append("--skip-searched" if settings["skip_searched"] else "--force-research")
    args.append("--filter-franchises" if settings["filter_franchises"] else "--no-filter-franchises")
    args.append("--require-website" if settings["require_website"] else "--no-require-website")
    args.append("--lead-enrichment" if settings["lead_enrichment"] else "--no-lead-enrichment")
    return args


def _scope_args(all_keywords, chosen_keywords, locations, coords) -> list[str]:
    args: list[str] = []
    names = list(all_keywords.keys()) if isinstance(all_keywords, dict) else list(all_keywords)
    if chosen_keywords and names and set(chosen_keywords) != set(names):
        args.extend(["--keywords", *chosen_keywords])
    all_locations = _locations(coords)
    if locations and len(locations) != len(all_locations):
        args.extend(_location_flags(locations))
    return args


def _location_flags(locations) -> list[str]:
    args: list[str] = []
    states = []
    cities = []
    for state, city in locations:
        if state not in states:
            states.append(state)
        if city not in cities:
            cities.append(city)
    for state in states:
        args.extend(["--state", state])
    for city in cities:
        args.extend(["--city", city])
    return args


def _prompt_keywords(keywords, reader, writer) -> list[str]:
    names = list(keywords.keys()) if isinstance(keywords, dict) else list(keywords)
    say(writer, "")
    say(writer, f"--- Keywords ({len(names)} in keywords.json) ---")
    say(writer, "1) All keywords")
    say(writer, "2) By industry group")
    say(writer, "3) Pick numbers / ranges")
    say(writer, "4) Search by name")
    choice = ask(reader, "Select [1]: ") or "1"
    if choice == "2":
        selected = _keywords_by_group(names, reader, writer)
    elif choice == "3":
        selected = _pick_numbered(names, reader, writer, "Keywords")
    elif choice == "4":
        needle = ask(reader, "Search text (matches keyword names): ").lower()
        matches = [name for name in names if needle and needle in name.lower()] or list(names)
        selected = _pick_numbered(matches, reader, writer, "Matches")
    else:
        selected = list(names)
    say(writer, f"Selected {len(selected)} keyword(s).")
    return selected


def _keywords_by_group(names, reader, writer) -> list[str]:
    present = []
    known = set(names)
    for key, label in _KEYWORD_GROUP_LABELS:
        group_names = [name for name in _KEYWORD_GROUPS.get(key, []) if name in known]
        if group_names:
            present.append((label, group_names))
    for index, (label, group_names) in enumerate(present, start=1):
        say(writer, f"{index}) {label} ({len(group_names)})")
    raw = ask(reader, "Group numbers or ranges (Enter for all groups): ")
    indices = parse_index_selection(raw, len(present))
    chosen = present if indices is None else [present[index] for index in indices]
    selected = []
    for _label, group_names in chosen:
        for name in group_names:
            if name not in selected:
                selected.append(name)
    return selected or list(names)


def _prompt_locations(coords, reader, writer):
    locations = _locations(coords)
    say(writer, "")
    say(writer, f"--- Locations ({len(locations)} cities in coords.json) ---")
    say(writer, "1) All cities")
    say(writer, "2) By state")
    say(writer, "3) Pick cities by number / range")
    choice = ask(reader, "Select [1]: ") or "1"
    if choice == "2":
        states = list(coords.keys()) if isinstance(coords, dict) else []
        for index, state in enumerate(states, start=1):
            count = len(coords.get(state) or {})
            say(writer, f"{index}) {state} ({count} cities)")
        raw = ask(reader, "State numbers, ranges, or codes (Enter for all): ")
        selected = _states_from_raw(raw, states)
        if selected is None:
            return locations
        return [(state, city) for state, city in locations if state in selected]
    if choice == "3":
        labels = [f"{city}, {state}" for state, city in locations]
        picked = _pick_numbered(labels, reader, writer, "Cities")
        wanted = set(picked)
        return [(state, city) for state, city in locations if f"{city}, {state}" in wanted]
    return locations


def _states_from_raw(raw, states):
    if not raw:
        return None
    selected = set()
    tokens = [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]
    numeric = ",".join(token for token in tokens if token.isdigit() or "-" in token)
    if numeric:
        indices = parse_index_selection(numeric, len(states))
        if indices is None:
            return None
        selected.update(states[index] for index in indices)
    for token in tokens:
        code = token.upper()
        if code in states:
            selected.add(code)
    return selected or None


def _pick_numbered(items, reader, writer, title) -> list:
    say(writer, f"--- {title} ---")
    for index, item in enumerate(items, start=1):
        say(writer, f"{index}) {item}")
    raw = ask(reader, "Numbers or ranges (Enter for all): ")
    indices = parse_index_selection(raw, len(items))
    if indices is None:
        return list(items)
    return [items[index] for index in indices] or list(items)


def _review_results(path: Path, reader, writer) -> None:
    """Sort, filter, and export niche JSON without importing niche_results (that imports the logger)."""
    if not path.is_file():
        say(writer, f"No results file at {path.name}")
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        say(writer, f"Could not read {path.name}: {exc}")
        return
    rows = payload if isinstance(payload, list) else list(payload.get("leads") or payload.get("results") or [])
    filters: dict = {}
    sort_key = "score"
    while True:
        visible = _sort_rows(_filter_rows(rows, filters), sort_key)
        say(writer, "")
        say(writer, f"{len(visible)} leads")
        for index, row in enumerate(visible[:25], start=1):
            name = str(row.get("business_name") or "")[:28]
            score = int(row.get("lead_score") or 0)
            say(writer, f"{index:>3} {score:>5}  {name}")
        if len(visible) > 25:
            say(writer, f"... {len(visible) - 25} more")
        say(writer, "s) Sort  f) Filter  v) View  e) Export CSV  c) Clear filters  q) Back")
        choice = ask(reader, "Select: ").lower() or "q"
        if choice in {"q", "b"}:
            return
        if choice == "s":
            raw = ask(reader, "Sort by score/reviews/rating [score]: ") or "score"
            if raw in {"score", "reviews", "rating"}:
                sort_key = raw
            continue
        if choice == "c":
            filters = {}
            continue
        if choice == "f":
            raw = ask(reader, "min score (blank=keep): ")
            if raw:
                filters["min_score"] = int(raw)
            raw = ask(reader, "min reviews (blank=keep): ")
            if raw:
                filters["min_reviews"] = int(raw)
            raw = ask(reader, "min rating (blank=keep): ")
            if raw:
                filters["min_rating"] = float(raw)
            continue
        if choice == "e":
            dest = ask(reader, "CSV path [niche_leads.csv]: ") or "niche_leads.csv"
            _export_csv(visible, Path(dest), writer)
            continue
        if choice == "v":
            raw = ask(reader, "Lead number: ")
            try:
                lead = visible[int(raw) - 1]
            except (ValueError, IndexError):
                say(writer, "Invalid lead number.")
                continue
            say(writer, str(lead.get("business_name") or ""))
            say(writer, f"Phone: {lead.get('phone_google') or lead.get('phone_website') or ''}")
            say(writer, f"Email: {lead.get('email') or ''}")
            say(writer, f"Website: {lead.get('website') or 'None'}")
            ask(reader, "Enter to return to the table: ")
            continue
        say(writer, "Unknown command.")


def _filter_rows(rows, filters):
    visible = []
    for row in rows:
        if "min_score" in filters and int(row.get("lead_score") or 0) < int(filters["min_score"]):
            continue
        if "min_reviews" in filters and int(row.get("user_ratings_total") or 0) < int(filters["min_reviews"]):
            continue
        if "min_rating" in filters and float(row.get("rating") or 0) < float(filters["min_rating"]):
            continue
        visible.append(row)
    return visible


def _sort_rows(rows, key):
    def value(row):
        if key == "reviews":
            return int(row.get("user_ratings_total") or 0)
        if key == "rating":
            return float(row.get("rating") or 0)
        return int(row.get("lead_score") or 0)

    return sorted(rows, key=value, reverse=True)


def _export_csv(rows, path: Path, writer) -> None:
    import csv

    with path.open("w", encoding="utf-8", newline="") as handle:
        out = csv.DictWriter(handle, fieldnames=("business_name", "phone", "email", "website", "lead_score"))
        out.writeheader()
        for row in rows:
            out.writerow(
                {
                    "business_name": row.get("business_name") or "",
                    "phone": row.get("phone_google") or row.get("phone_website") or "",
                    "email": row.get("email") or "",
                    "website": row.get("website") or "",
                    "lead_score": row.get("lead_score") if row.get("lead_score") is not None else "",
                }
            )
    say(writer, f"Wrote {path}")


def _prompt_int(reader, label, default) -> int:
    raw = ask(reader, f"{label} [{default}]: ")
    if not raw:
        return int(default)
    try:
        return int(raw)
    except ValueError:
        return int(default)


def _locations(coords) -> list[tuple[str, str]]:
    locations = []
    if not isinstance(coords, dict):
        return locations
    for state, cities in coords.items():
        if isinstance(cities, dict):
            for city in cities:
                locations.append((str(state), str(city)))
    return locations


def _niche_list(niches) -> list[dict]:
    if isinstance(niches, dict):
        items = []
        for key, value in niches.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("id", key)
                items.append(item)
        return sorted(items, key=lambda item: (item.get("sort_order", 1000), str(item.get("display_name") or "")))
    if isinstance(niches, list):
        return [item for item in niches if isinstance(item, dict)]
    return []


def _load_settings(path: Path) -> dict:
    settings = dict(_DEFAULTS)
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            loaded = {}
        if isinstance(loaded, dict):
            for key in _DEFAULTS:
                if key in loaded:
                    settings[key] = loaded[key]
    return settings


def _save_settings(settings: dict, path: Path, writer) -> None:
    payload = {key: settings.get(key, default) for key, default in _DEFAULTS.items()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    say(writer, f"Defaults saved to {path.name}.")


def _load_json(path: Path, fallback):
    if not path.is_file():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback
