"""leadgen_cli implementation for leadgen.

Executed into the leadgen module so imports and patches of leadgen.*
keep resolving there. This file is not an import target.
"""
from scripts.lead_automation.search_input import (
    EMPTY_NICHE_MESSAGE,
    EMPTY_SEARCH_MESSAGE,
    EmptySearchInput,
    allocate_output_paths,
    build_search_queries,
    is_presets_choice,
    lead_types_for_filename,
    output_directory,
    parse_term_list,
    places_keyword,
    queries_for_location,
    require_niches,
)

def _is_contacted(row, contacted_emails):
    """True if any email on the row has already been contacted."""
    emails = [e.strip().lower() for e in (row.get("email") or "").split(";") if e.strip()]
    return any(email in contacted_emails for email in emails)


def _prompt_int(prompt, default):
    raw = input(f"{prompt} [{default}]: ").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"Invalid number, using default {default}.")
        return default


def _prompt_bool(prompt, default=True):
    default_label = "Y/n" if default else "y/N"
    raw = input(f"{prompt} [{default_label}]: ").strip().lower()
    if not raw:
        return default
    if raw in ("y", "yes", "true", "1"):
        return True
    if raw in ("n", "no", "false", "0"):
        return False
    print(f"Invalid choice, using default {default}.")
    return default


def _prompt_output_mode(default="json"):
    labels = {"1": "json", "2": "dashboard", "3": "both"}
    default_num = {"json": "1", "dashboard": "2", "both": "3"}.get(default, "1")
    raw = input(f"Output: 1=JSON  2=Dashboard  3=Both [{default_num}]: ").strip()
    if not raw:
        return default
    return labels.get(raw, default)


def _prompt_leadgen_type(default=DEFAULT_LEADGEN_TYPE):
    labels = {"1": "api_manager", "2": "playwright"}
    default_num = {"api_manager": "1", "playwright": "2"}.get(
        normalize_leadgen_type(default), "1"
    )
    raw = input(
        f"Leadgen type: 1=API Manager  2=Playwright [{default_num}]: "
    ).strip()
    if not raw:
        return normalize_leadgen_type(default)
    return labels.get(raw, normalize_leadgen_type(default))


def _prompt_area_expansion(default=DEFAULT_PLAYWRIGHT_AREA_EXPANSION):
    labels = {"1": "off", "2": "light", "3": "dense"}
    current = normalize_area_expansion(default)
    default_num = {"off": "1", "light": "2", "dense": "3"}.get(current, "1")
    raw = input(
        "Area expansion (more leads per city): "
        "1=off  2=light (~5 map cells)  3=dense (~9 cells) "
        f"[{default_num}]: "
    ).strip()
    if not raw:
        return current
    return labels.get(raw, current)


def _prompt_objective(default="phone"):
    labels = {"1": "phone", "2": "email", "3": "either", "4": "both"}
    default_num = {"phone": "1", "email": "2", "either": "3", "both": "4"}.get(default, "1")
    raw = input(
        f"Objective: 1=phone  2=email  3=either  4=both [{default_num}]: "
    ).strip()
    if not raw:
        return normalize_objective(default)
    return labels.get(raw, normalize_objective(default))


def _prompt_text(prompt, default):
    raw = input(f"{prompt} [{default}]: ").strip()
    return raw if raw else default


def _locations_by_state(coords_data=None):
    """Return {state: [(city, coords), ...]} from coords.json data."""
    data = coords_data if coords_data is not None else COORDS_DATA
    grouped = {}
    for state, cities in data.items():
        grouped[state] = [(city, coords) for city, coords in cities.items()]
    return grouped


def _parse_index_selection(raw, max_index):
    """Parse '1,3,5' or '1-4,8' into 0-based indices.

    Empty / 'all' means all (returns None). 'none' means nothing (returns []).
    """
    if not raw or not raw.strip():
        return None
    lowered = raw.strip().lower()
    if lowered in ("all", "*"):
        return None
    if lowered in ("none", "n"):
        return []
    indices = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part and not part.startswith("-"):
            ends = part.split("-", 1)
            try:
                start = int(ends[0].strip())
                end = int(ends[1].strip())
            except ValueError:
                continue
            if start > end:
                start, end = end, start
            for number in range(start, end + 1):
                idx = number - 1
                if 0 <= idx < max_index and idx not in indices:
                    indices.append(idx)
            continue
        try:
            idx = int(part) - 1
            if 0 <= idx < max_index and idx not in indices:
                indices.append(idx)
        except ValueError:
            continue
    return indices


def _terminal_width(fallback=80):
    try:
        return max(40, shutil.get_terminal_size(fallback=(fallback, 24)).columns)
    except Exception:
        return fallback


def _format_numbered_items_horizontal(items, width=None):
    """Format '1) label  2) label ...' wrapping across terminal width."""
    if width is None:
        width = _terminal_width()
    lines = []
    current = ""
    for i, label in enumerate(items, 1):
        cell = f"{i}) {label}"
        if not current:
            current = cell
            continue
        candidate = f"{current}  {cell}"
        if len(candidate) <= width:
            current = candidate
        else:
            lines.append(current)
            current = cell
    if current:
        lines.append(current)
    return "\n".join(lines)


def _prompt_choice(title, options, default="1"):
    """Numbered single-choice prompt. options is [(key, label), ...]."""
    print(f"\n{title}")
    keys = []
    for key, label in options:
        keys.append(str(key))
        print(f"{key}) {label}")
    raw = input(f"Select [{default}]: ").strip() or str(default)
    if raw in keys:
        return raw
    print(f"Invalid choice, using {default}.")
    return str(default)


def _prompt_keyword_groups(keyword_map):
    keys = list(keyword_map.keys())
    present_groups = []
    for group, label in KEYWORD_GROUP_LABELS.items():
        names = [kw for kw in KEYWORD_GROUPS.get(group, []) if kw in keyword_map]
        extra = [kw for kw in keys if keyword_group_for(kw) == group and kw not in names]
        names.extend(extra)
        if names:
            present_groups.append((group, label, names))
    print("\nIndustry groups:")
    labels = [
        f"{label} ({len(names)})" for _group, label, names in present_groups
    ]
    print(_format_numbered_items_horizontal(labels))
    raw = input(
        "Enter group numbers or ranges (e.g. 1-3,5), or Enter for all groups: "
    ).strip()
    indices = _parse_index_selection(raw, len(present_groups))
    chosen = present_groups if indices is None else [
        present_groups[i] for i in indices
    ]
    selected = []
    seen = set()
    for _group, _label, names in chosen:
        for kw in names:
            if kw not in seen:
                seen.add(kw)
                selected.append(kw)
    return selected or list(keys)


def _prompt_keyword_numbers(keyword_map):
    keys = list(keyword_map.keys())
    print("\n--- Keywords ---")
    print(_format_numbered_items_horizontal(keys))
    raw = input(
        "Enter numbers/ranges (e.g. 1-8,12) or press Enter for all: "
    ).strip()
    indices = _parse_index_selection(raw, len(keys))
    if indices is None:
        return list(keys)
    return [keys[i] for i in indices] or list(keys)


def _prompt_keyword_search(keyword_map):
    keys = list(keyword_map.keys())
    needle = input("Search text (matches keyword names): ").strip().lower()
    if not needle:
        print("No search text; using all keywords.")
        return list(keys)
    matches = [kw for kw in keys if needle in kw.lower()]
    if not matches:
        print("No keywords matched; using all.")
        return list(keys)
    print(f"\nMatched {len(matches)} keyword(s):")
    print(_format_numbered_items_horizontal(matches))
    raw = input("Enter numbers/ranges from this list, or Enter for all matches: ").strip()
    indices = _parse_index_selection(raw, len(matches))
    if indices is None:
        return matches
    return [matches[i] for i in indices] or matches


def _prompt_keywords(keyword_map):
    """Prompt user to select keywords from keywords.json."""
    keys = list(keyword_map.keys())
    print(f"\n--- Keywords ({len(keys)} in keywords.json) ---")
    choice = _prompt_choice(
        "How do you want to choose keywords?",
        [
            ("1", f"All {len(keys)} keywords  (best for volume)"),
            ("2", "By industry group"),
            ("3", "Pick numbers / ranges  (e.g. 1-8,12)"),
            ("4", "Search by name"),
        ],
        default="1",
    )
    if choice == "2":
        selected = _prompt_keyword_groups(keyword_map)
    elif choice == "3":
        selected = _prompt_keyword_numbers(keyword_map)
    elif choice == "4":
        selected = _prompt_keyword_search(keyword_map)
    else:
        selected = list(keys)
    print(f"Selected {len(selected)} keyword(s).")
    return selected


def _prompt_locations_by_state(all_locations):
    by_state = _locations_by_state()
    states = list(by_state.keys())
    print("\nStates:")
    labels = [
        f"{state} ({len(cities)} cities)" for state, cities in by_state.items()
    ]
    print(_format_numbered_items_horizontal(labels))
    raw = input(
        "Enter state numbers, ranges, or codes (e.g. 1-3 or NJ,PA). Enter for all: "
    ).strip()
    if not raw:
        return list(all_locations)
    selected_states = set()
    tokens = [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]
    numeric_raw = ",".join(t for t in tokens if t.isdigit() or "-" in t)
    code_tokens = [t.upper() for t in tokens if not (t.isdigit() or "-" in t)]
    if numeric_raw:
        indices = _parse_index_selection(numeric_raw, len(states))
        if indices is None:
            return list(all_locations)
        selected_states.update(states[i] for i in indices)
    for code in code_tokens:
        if code in by_state:
            selected_states.add(code)
        else:
            print(f"Unknown state '{code}', ignored.")
    if not selected_states:
        print("No states matched; using all locations.")
        return list(all_locations)
    selected = [
        loc for loc in all_locations if loc[0] in selected_states
    ]
    return selected or list(all_locations)


def _prompt_location_numbers(all_locations):
    by_state = _locations_by_state()
    print("\n--- Locations (coords.json) ---")
    index_map = []
    for state, cities in by_state.items():
        print(f"\n{state}:")
        state_items = []
        for city, coords in cities:
            index_map.append((state, city, coords))
            state_items.append(city)
        start = len(index_map) - len(state_items) + 1
        width = _terminal_width()
        current = ""
        lines = []
        for offset, city in enumerate(state_items):
            cell = f"{start + offset}) {city}"
            if not current:
                current = cell
                continue
            candidate = f"{current}  {cell}"
            if len(candidate) <= width:
                current = candidate
            else:
                lines.append(current)
                current = cell
        if current:
            lines.append(current)
        print("\n".join(lines))
    raw = input(
        "\nEnter numbers/ranges (e.g. 1-4,7) or press Enter for all: "
    ).strip()
    indices = _parse_index_selection(raw, len(index_map))
    if indices is None:
        return list(all_locations)
    selected = [index_map[i] for i in indices]
    return selected or list(all_locations)


def _prompt_locations(all_locations):
    """Prompt user to select locations from coords.json."""
    print(f"\n--- Locations ({len(all_locations)} cities in coords.json) ---")
    choice = _prompt_choice(
        "How do you want to choose locations?",
        [
            ("1", f"All {len(all_locations)} cities  (best for volume)"),
            ("2", "By state  (numbers or codes like NJ, PA)"),
            ("3", "Pick cities by number / range"),
        ],
        default="1",
    )
    if choice == "2":
        selected = _prompt_locations_by_state(all_locations)
    elif choice == "3":
        selected = _prompt_location_numbers(all_locations)
    else:
        selected = list(all_locations)
    print(
        f"Selected {len(selected)} location(s): "
        + ", ".join(f"{city}, {state}" for state, city, _ in selected[:12])
        + ("..." if len(selected) > 12 else "")
    )
    return selected


def interactive_select_locations_and_keywords():
    """Return (keywords, locations) from the optional keywords.json presets."""
    keywords = _prompt_keywords(KEYWORD_CATEGORIES)
    locations = _prompt_locations(_default_locations())
    return keywords, locations


def _prompt_free_text_niches():
    """Ask for niches. Return 'presets' or a list. Re-prompts when the line is empty."""
    print("\nBusiness niche(s), comma-separated.")
    print("Example: mobile dog grooming")
    print("Type presets to choose from keywords.json instead.")
    while True:
        try:
            raw = input("Business niche(s): ")
        except EOFError:
            raise SystemExit(2)
        if is_presets_choice(raw):
            return "presets"
        try:
            return require_niches(raw)
        except EmptySearchInput as exc:
            print(exc)


def _prompt_free_text_keywords():
    print("\nKeyword search string(s), comma-separated.")
    print("Leave blank to search each niche in the locations you pick.")
    print("Example: pressure washing near Cherry Hill NJ")
    try:
        raw = input("Keyword search string(s): ")
    except EOFError:
        raise SystemExit(2)
    return parse_term_list(raw)


def apply_free_text_search(config, niches, keywords, today=None, explicit_json=False):
    """Point a run at the typed niche and keyword strings and a new output name."""
    niches = parse_term_list(niches)
    keywords = parse_term_list(keywords)
    if not niches and not keywords:
        raise EmptySearchInput(EMPTY_SEARCH_MESSAGE)
    queries = build_search_queries(niches, keywords, config.locations)
    if not queries:
        raise EmptySearchInput(EMPTY_SEARCH_MESSAGE)
    config.niches = list(niches)
    config.keywords = queries
    config.exact_queries = True
    if explicit_json:
        if not getattr(config, "csv_output", ""):
            config.csv_output = str(Path(config.json_output).with_suffix(".csv"))
        return config
    directory = output_directory(config.json_output)
    csv_path, json_path = allocate_output_paths(
        directory,
        lead_types_for_filename(niches, keywords),
        today=today,
    )
    config.json_output = str(json_path)
    config.csv_output = str(csv_path)
    return config


def keywords_for_location(config, city, state):
    """Keyword strings to run at one city. Exact queries are not repeated everywhere."""
    keywords = list(config.keywords or [])
    if not getattr(config, "exact_queries", False):
        return keywords
    return queries_for_location(keywords, city, state, config.locations or [])


def interactive_free_text_run():
    """Prompt for a niche and keywords, then return a config or None if cancelled."""
    cfg = config_from_saved_settings()
    print("\n=== Lead Generation ===")
    print("Type a business niche and, if you want, the exact search strings.")
    print("keywords.json is optional. Any niche works, including ones that are not configured.")
    choice = _prompt_free_text_niches()
    if choice == "presets":
        if not KEYWORD_CATEGORIES:
            print("keywords.json has no presets. Type a niche instead.")
            choice = _prompt_free_text_niches()
            if choice == "presets":
                print(EMPTY_NICHE_MESSAGE)
                return None
        else:
            cfg.keywords, cfg.locations = interactive_select_locations_and_keywords()
            cfg.discovery_mode = "standard"
            _print_config_summary(cfg)
            confirm = input("Run with these settings? [Y/n]: ").strip().lower()
            if confirm in ("n", "no"):
                return None
            return cfg
    niches = choice
    keywords = _prompt_free_text_keywords()
    cfg.locations = _prompt_locations(_default_locations())
    cfg.discovery_mode = "standard"
    try:
        apply_free_text_search(cfg, niches, keywords)
    except EmptySearchInput as exc:
        print(exc)
        return None
    _print_config_summary(cfg)
    confirm = input("Run with these settings? [Y/n]: ").strip().lower()
    if confirm in ("n", "no"):
        return None
    return cfg


def interactive_customize_config(base_config=None):
    """Edit persisted defaults from a numbered menu (no keywords/locations)."""
    cfg = base_config or config_from_saved_settings()
    while True:
        print("\n--- Settings (enter a number to change, Enter to save) ---")
        items = [
            ("1", "Leadgen type", normalize_leadgen_type(cfg.leadgen_type)),
            ("2", "Playwright max pages", cfg.playwright_max_pages),
            ("3", "Max results per search", cfg.playwright_max_results_per_search),
            (
                "4",
                "Area expansion",
                normalize_area_expansion(cfg.playwright_area_expansion),
            ),
            ("5", "Skip already searched", cfg.skip_searched),
            ("6", "Search history path", cfg.search_history_path),
            ("7", "Minimum score", cfg.min_score),
            ("8", "Minimum reviews", cfg.min_reviews),
            ("9", "Filter franchises", cfg.filter_franchises),
            ("10", "Objective", cfg.objective),
            ("11", "Require website", cfg.require_website),
            (
                "12",
                (
                    "Lead enrichment (Google/Playwright)"
                    if normalize_leadgen_type(cfg.leadgen_type) == "playwright"
                    else "Lead enrichment (Facebook)"
                ),
                cfg.lead_enrichment,
            ),
            ("13", "Output", cfg.output_mode),
            ("14", "JSON output path", cfg.json_output),
        ]
        width = max(len(label) for _num, label, _val in items)
        for num, label, value in items:
            print(f" {num:>2}) {label:<{width}}  [{value}]")
        raw = input("Change setting [Enter=save & return]: ").strip()
        if not raw:
            return cfg
        if raw == "1":
            cfg.leadgen_type = _prompt_leadgen_type(cfg.leadgen_type)
        elif raw == "2":
            cfg.playwright_max_pages = _prompt_int(
                "Playwright max pages per search",
                cfg.playwright_max_pages,
            )
        elif raw == "3":
            cfg.playwright_max_results_per_search = _prompt_int(
                "Playwright max results per search",
                cfg.playwright_max_results_per_search,
            )
        elif raw == "4":
            cfg.playwright_area_expansion = _prompt_area_expansion(
                cfg.playwright_area_expansion
            )
        elif raw == "5":
            cfg.skip_searched = _prompt_bool(
                "Skip keyword/location searches already in history",
                cfg.skip_searched,
            )
        elif raw == "6":
            cfg.search_history_path = _prompt_text(
                "Search history path",
                cfg.search_history_path,
            )
        elif raw == "7":
            cfg.min_score = _prompt_int("Minimum score", cfg.min_score)
        elif raw == "8":
            cfg.min_reviews = _prompt_int("Minimum review count", cfg.min_reviews)
        elif raw == "9":
            cfg.filter_franchises = _prompt_bool(
                "Filter out franchises/chains",
                cfg.filter_franchises,
            )
        elif raw == "10":
            cfg.objective = _prompt_objective(cfg.objective)
        elif raw == "11":
            cfg.require_website = _prompt_bool("Require website", cfg.require_website)
        elif raw == "12":
            enrich_prompt = (
                "Lead enrichment (Google search + website/SEO research)"
                if normalize_leadgen_type(cfg.leadgen_type) == "playwright"
                else "Lead enrichment (find missing emails on Facebook)"
            )
            cfg.lead_enrichment = _prompt_bool(enrich_prompt, cfg.lead_enrichment)
        elif raw == "13":
            cfg.output_mode = _prompt_output_mode(cfg.output_mode)
        elif raw == "14":
            cfg.json_output = _prompt_text("JSON output path", cfg.json_output)
        else:
            print("Enter a setting number from the list, or press Enter to save.")


def _print_volume_estimate(config):
    stats = estimate_discovery_volume(config)
    print("\n--- Volume estimate ---")
    if stats.get("exact_queries"):
        print(
            f"  {stats['keywords']} search string(s) across {stats['locations']} location(s)"
            + (
                f" x {stats['areas_per_search']} map cells"
                if stats["leadgen_type"] == "playwright"
                else ""
            )
            + f" = {stats['searches']} searches"
        )
    else:
        print(
            f"  {stats['keywords']} keywords x {stats['locations']} cities"
            + (
                f" x {stats['areas_per_search']} map cells"
                if stats["leadgen_type"] == "playwright"
                else ""
            )
            + f" = {stats['searches']} searches"
        )
    print(
        f"  Typical unique businesses: {stats['unique_low']:,}-{stats['unique_high']:,}"
    )
    print(
        "  After quality filters, expect hundreds of leads from a few cities, "
        "or thousands from many keywords x many cities."
    )
    if stats["searches"] >= 200:
        print(
            "  Note: Playwright volume runs can take hours; skip-searched "
            "lets you resume later."
        )


def _print_config_summary(config, include_run_scope=True):
    print("\n--- Configuration ---")
    print(f"  Leadgen type:      {normalize_leadgen_type(config.leadgen_type)}")
    if normalize_leadgen_type(config.leadgen_type) == "playwright":
        print(f"  Playwright pages:  {config.playwright_max_pages}")
        print(
            f"  Playwright max:    {config.playwright_max_results_per_search} results/search"
        )
        print(
            f"  Area expansion:    {normalize_area_expansion(config.playwright_area_expansion)}"
        )
    print(f"  Skip searched:     {config.skip_searched}")
    print(f"  Search history:    {config.search_history_path}")
    print(f"  Min score:         {config.min_score}")
    print(f"  Min reviews:       {config.min_reviews}")
    print(f"  Filter franchises: {config.filter_franchises}")
    print(f"  Objective:         {config.objective}")
    print(f"  Require website:   {config.require_website}")
    print(f"  Lead enrichment:   {config.lead_enrichment}")
    print(f"  Output:            {config.output_mode}")
    print(f"  JSON path:         {config.json_output}")
    if getattr(config, "csv_output", ""):
        print(f"  CSV path:          {config.csv_output}")
    if include_run_scope:
        if getattr(config, "niches", None):
            print(f"  Niches ({len(config.niches)}): {', '.join(config.niches)}")
        print(f"  Keywords ({len(config.keywords)}): {', '.join(config.keywords)}")
        locs = ", ".join(f"{city}, {state}" for state, city, _ in config.locations)
        print(f"  Locations ({len(config.locations)}): {locs}")
        _print_volume_estimate(config)
    print()


def interactive_new_business():
    """Configure a new-business run from the same menu as keyword discovery."""
    cfg = config_from_saved_settings()
    cfg.discovery_mode = "new-business"
    print("\nNew-business discovery")
    print("Searches public registration and license sources for newly formed businesses.")
    print("Keyword Google Maps search is not used.")
    cfg.locations = _prompt_locations(_default_locations())
    cfg.nb_max_age_days = _prompt_int("Max age in days", cfg.nb_max_age_days)
    cfg.nb_min_score = _prompt_int("Minimum new-business score", cfg.nb_min_score)
    if cfg.json_output in ("leads_output.json", "", None):
        cfg.json_output = "new_business_leads.json"
    if cfg.output_mode == "dashboard":
        print("Dashboard output is not used for new-business discovery. Writing JSON and CSV.")
        cfg.output_mode = "both"
    locs = ", ".join(f"{city}, {state}" for state, city, _coords in cfg.locations[:12])
    print(f"\nLocations: {locs}")
    print(f"Max age: {cfg.nb_max_age_days} days | min score {cfg.nb_min_score}")
    print(f"JSON: {cfg.json_output}")
    print(f"CSV: {cfg.nb_csv_output}")
    confirm = input("Run new-business discovery? [Y/n]: ").strip().lower()
    if confirm in ("n", "no"):
        return None
    return cfg


def interactive_run_config():
    """Load saved defaults, prompt keywords/locations, return config or None if cancelled."""
    cfg = config_from_saved_settings()
    while True:
        cfg.keywords, cfg.locations = interactive_select_locations_and_keywords()
        _print_config_summary(cfg)
        confirm = input(
            "Run with these settings? [Y/n/s=settings]: "
        ).strip().lower()
        if confirm in ("n", "no"):
            return None
        if confirm in ("s", "settings"):
            cfg = interactive_customize_config(cfg)
            save_settings(cfg)
            continue
        return cfg


def interactive_main_menu():
    """Show startup menu and return a LeadgenConfig, or None to exit."""
    while True:
        cfg_preview = config_from_saved_settings()
        leadgen_type = normalize_leadgen_type(cfg_preview.leadgen_type)
        print("\n=== Lead Generation ===")
        print(
            f"  Current: {leadgen_type} | objective={cfg_preview.objective} | "
            f"min score {cfg_preview.min_score} | output {cfg_preview.output_mode}"
        )
        if leadgen_type == "playwright":
            print(
                f"  Playwright: {cfg_preview.playwright_max_pages} pages, "
                f"{cfg_preview.playwright_max_results_per_search} max/search, "
                f"expansion={normalize_area_expansion(cfg_preview.playwright_area_expansion)}"
            )
        print()
        print("1) Run (choose keywords & locations)")
        print("2) Settings (save defaults, do not run)")
        print("3) High-volume preset (Playwright, area expansion, no Facebook enrich)")
        print("4) Exit")
        print("5) Lead Search (micro-niche intent search)")
        print("6) New-business discovery")
        choice = input("Select [1]: ").strip() or "1"
        if choice == "5":
            from niche_search import interactive_niche_search
            interactive_niche_search(cfg_preview)
            continue
        if choice == "4":
            return None
        if choice == "2":
            cfg = interactive_customize_config()
            save_settings(cfg)
            _print_config_summary(cfg, include_run_scope=False)
            print(f"Defaults saved to {SETTINGS_PATH.name}. Returning to menu.")
            continue
        if choice == "3":
            cfg = apply_high_volume_preset(config_from_saved_settings())
            save_settings(cfg)
            print("\nApplied high-volume Playwright preset.")
            _print_config_summary(cfg, include_run_scope=False)
            go = input("Choose keywords & locations and run now? [Y/n]: ").strip().lower()
            if go in ("n", "no"):
                print(f"Defaults saved to {SETTINGS_PATH.name}. Returning to menu.")
                continue
            return interactive_run_config()
        if choice == "6":
            return interactive_new_business()
        if choice == "1":
            cfg = interactive_run_config()
            if cfg is not None:
                cfg.discovery_mode = "standard"
            return cfg
        print("Invalid choice. Please select 1, 2, 3, 4, 5, or 6.")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Local business lead generation")
    parser.add_argument(
        "--defaults",
        action="store_true",
        help="Skip interactive menu and use defaults",
    )
    parser.add_argument(
        "--leadgen-type",
        choices=list(VALID_LEADGEN_TYPES),
        default=None,
        help=(
            "Business discovery provider: playwright (browser Maps search) or "
            f"api_manager (Google Places API; default {DEFAULT_LEADGEN_TYPE})"
        ),
    )
    parser.add_argument(
        "--playwright-max-pages",
        type=int,
        default=None,
        help=(
            "Max result pages to process per keyword/location in Playwright mode "
            f"(default {DEFAULT_PLAYWRIGHT_MAX_PAGES})"
        ),
    )
    parser.add_argument(
        "--playwright-max-results-per-search",
        type=int,
        default=None,
        help=(
            "Max businesses to collect per keyword/location in Playwright mode "
            f"(default {DEFAULT_PLAYWRIGHT_MAX_RESULTS_PER_SEARCH})"
        ),
    )
    parser.add_argument(
        "--playwright-area-expansion",
        choices=list(VALID_AREA_EXPANSIONS),
        default=None,
        help=(
            "Extra map cells around each city to break Maps' ~120 result cap: "
            "off, light (~5 cells), or dense (~9 cells)"
        ),
    )
    parser.add_argument(
        "--skip-searched",
        dest="skip_searched",
        action="store_true",
        default=None,
        help="Skip keyword/location combos already recorded in search history (default)",
    )
    parser.add_argument(
        "--force-research",
        dest="skip_searched",
        action="store_false",
        help="Re-run searches even if they appear in search history",
    )
    parser.add_argument(
        "--search-history-path",
        default=None,
        help=f"Path to search history JSON (default {DEFAULT_HISTORY_PATH})",
    )
    parser.add_argument("--min-score", type=int, help="Minimum lead_score to keep (default 80)")
    parser.add_argument(
        "--min-reviews",
        type=int,
        help="Minimum user_ratings_total to keep (default 5)",
    )
    parser.add_argument(
        "--filter-franchises",
        dest="filter_franchises",
        action="store_true",
        default=None,
        help="Exclude franchise/chain leads (default)",
    )
    parser.add_argument(
        "--no-filter-franchises",
        dest="filter_franchises",
        action="store_false",
        help="Allow franchise/chain leads",
    )
    parser.add_argument(
        "--objective",
        choices=list(VALID_OBJECTIVES),
        default=None,
        help="Hard contact requirement: phone, email, either, or both (default phone)",
    )
    parser.add_argument(
        "--require-phone",
        dest="require_phone",
        action="store_true",
        default=None,
        help="Legacy alias: require a valid phone (maps to --objective)",
    )
    parser.add_argument(
        "--no-require-phone",
        dest="require_phone",
        action="store_false",
        help="Legacy alias: do not require a phone (maps to --objective)",
    )
    parser.add_argument(
        "--require-website",
        dest="require_website",
        action="store_true",
        default=None,
        help="Require a website URL from Place Details",
    )
    parser.add_argument(
        "--no-require-website",
        dest="require_website",
        action="store_false",
        help="Allow leads without a website (default)",
    )
    parser.add_argument(
        "--require-email",
        dest="require_email",
        action="store_true",
        default=None,
        help="Legacy alias: require an email (maps to --objective)",
    )
    parser.add_argument(
        "--no-require-email",
        dest="require_email",
        action="store_false",
        help="Legacy alias: do not require an email (maps to --objective)",
    )
    parser.add_argument(
        "--lead-enrichment",
        dest="lead_enrichment",
        action="store_true",
        default=None,
        help="Run post-scrape enrichment (Facebook in API mode, Google/Playwright in Playwright mode; default on)",
    )
    parser.add_argument(
        "--no-lead-enrichment",
        dest="lead_enrichment",
        action="store_false",
        help="Skip post-scrape enrichment",
    )
    parser.add_argument(
        "--output",
        choices=["json", "csv", "dashboard", "both"],
        help="Output destination (new-business: json, csv, or both; standard both is JSON + dashboard)",
    )
    parser.add_argument("--json-path", help="JSON output path. Omit to name the file from today's date and the niche")
    parser.add_argument(
        "--keywords",
        nargs="+",
        help="Free-text keyword search strings. Commas are allowed. Not limited to keywords.json",
    )
    parser.add_argument(
        "--city",
        action="append",
        help="City name filter (repeatable); matches coords.json city names",
    )
    parser.add_argument(
        "--state",
        action="append",
        help="State code filter (repeatable); matches coords.json keys like NJ, PA",
    )
    parser.add_argument(
        "--niche",
        action="append",
        help=(
            "Business niche free text, repeatable or comma-separated "
            "(example: mobile dog grooming). A single niches.json id still runs "
            "Niche Lead Search unless --free-text or --keywords is set"
        ),
    )
    parser.add_argument(
        "--free-text",
        action="store_true",
        help="Search the typed --niche and --keywords with the normal lead criteria",
    )
    parser.add_argument(
        "--review-leads",
        action="store_true",
        help="Open the Niche Lead Search results reviewer (no new search)",
    )
    parser.add_argument(
        "--zip",
        action="append",
        dest="zips",
        help="ZIP code to include in a niche search (repeatable)",
    )
    parser.add_argument(
        "--radius",
        type=int,
        help="Niche search radius in meters (default 50000)",
    )
    parser.add_argument(
        "--max-leads",
        type=int,
        help="Cap ranked niche leads after scoring",
    )
    parser.add_argument(
        "--min-rating",
        type=float,
        help="Minimum Google rating for niche search",
    )
    parser.add_argument(
        "--exclude-strong-websites",
        action="store_true",
        default=None,
        help="Drop niche leads with a strong current website",
    )
    parser.add_argument(
        "--require-social",
        action="store_true",
        default=None,
        help="Require a Facebook or Instagram URL on niche leads",
    )
    parser.add_argument(
        "--require-no-website",
        action="store_true",
        default=None,
        help="Keep only niche leads with no usable website",
    )
    parser.add_argument(
        "--require-website-issue",
        action="store_true",
        default=None,
        help="Keep only niche leads whose website quality is poor/critical",
    )
    parser.add_argument(
        "--require-active-business",
        dest="require_active_business",
        action="store_true",
        default=None,
        help="Drop closed businesses in niche search (default on)",
    )
    parser.add_argument(
        "--allow-inactive-business",
        dest="require_active_business",
        action="store_false",
        help="Allow closed/unknown businesses in niche search",
    )
    parser.add_argument(
        "--website-requirement",
        choices=["any", "none", "weak_or_none", "issue"],
        default=None,
        help="Niche website filter: any, none, weak_or_none, or issue",
    )
    parser.add_argument(
        "--extra-keywords",
        nargs="+",
        help="Additional niche search queries",
    )
    parser.add_argument(
        "--mode",
        choices=["standard", "new-business"],
        default=None,
        help="standard keeps keyword discovery; new-business finds newly registered businesses",
    )
    parser.add_argument("--max-age-days", type=int, default=None, help="New-business age window in days (default 365)")
    parser.add_argument("--very-new-days", type=int, default=None, help="Top newness tier in days (default 90)")
    parser.add_argument(
        "--sources",
        default=None,
        help="Comma-separated new-business source ids (default: all enabled verified sources)",
    )
    parser.add_argument("--list-sources", action="store_true", help="Print new-business sources and exit")
    parser.add_argument("--county", action="append", default=None, help="County filter for new-business records (repeatable)")
    parser.add_argument("--region", default=None, help="Region name from geo_regions.json")
    parser.add_argument("--regions-file", default=None, help="Path to geo_regions.json")
    parser.add_argument("--min-new-business-score", type=int, default=None, help="Minimum new_business_score (default 50)")
    parser.add_argument("--score-rules", default=None, help="Path to new_business_score_rules.json")
    parser.add_argument(
        "--website-check",
        choices=["none", "cheap", "deep"],
        default=None,
        help="Website check depth for new-business mode (default deep)",
    )
    parser.add_argument("--refresh-enrichment", action="store_true", help="Ignore the new-business email cache TTL")
    parser.add_argument("--include-seen", action="store_true", help="Re-output businesses already written by new-business mode")
    parser.add_argument("--csv-path", default=None, help="CSV path for new-business mode (default new_business_leads.csv)")
    parser.add_argument("--max-records-per-source", type=int, default=None, help="Cap records fetched from each source (default 200)")
    parser.add_argument("--dry-run", action="store_true", help="New-business fixtures only; no network")
    parser.add_argument("--headful", action="store_true", help="Show the browser for Playwright new-business adapters")
    parser.add_argument("--no-artifacts", action="store_true", help="Do not write new_business_artifacts on errors")
    return parser.parse_args(argv)


def _has_cli_overrides(args):
    return any([
        args.defaults,
        args.leadgen_type is not None,
        args.playwright_max_pages is not None,
        args.playwright_max_results_per_search is not None,
        args.playwright_area_expansion is not None,
        args.skip_searched is not None,
        args.search_history_path is not None,
        args.min_score is not None,
        args.min_reviews is not None,
        args.filter_franchises is not None,
        args.objective is not None,
        args.require_phone is not None,
        args.require_website is not None,
        args.require_email is not None,
        args.lead_enrichment is not None,
        args.output is not None,
        args.json_path is not None,
        args.keywords is not None,
        args.city is not None,
        args.state is not None,
        bool(getattr(args, "niche", None)),
        bool(getattr(args, "free_text", False)),
        getattr(args, "mode", None) is not None,
        getattr(args, "max_age_days", None) is not None,
        getattr(args, "very_new_days", None) is not None,
        getattr(args, "sources", None) is not None,
        getattr(args, "county", None) is not None,
        getattr(args, "region", None) is not None,
        getattr(args, "min_new_business_score", None) is not None,
        getattr(args, "dry_run", False),
        getattr(args, "csv_path", None) is not None,
    ])


def config_from_args(args):
    """Build LeadgenConfig from saved defaults plus argparse overrides."""
    config = config_from_saved_settings()
    if args.leadgen_type is not None:
        config.leadgen_type = normalize_leadgen_type(args.leadgen_type)
    if args.playwright_max_pages is not None:
        config.playwright_max_pages = max(1, int(args.playwright_max_pages))
    if args.playwright_max_results_per_search is not None:
        config.playwright_max_results_per_search = max(
            1, int(args.playwright_max_results_per_search)
        )
    if args.playwright_area_expansion is not None:
        config.playwright_area_expansion = normalize_area_expansion(
            args.playwright_area_expansion
        )
    if args.skip_searched is not None:
        config.skip_searched = bool(args.skip_searched)
    if args.search_history_path is not None:
        config.search_history_path = str(args.search_history_path)
    if args.min_score is not None:
        config.min_score = args.min_score
    if args.min_reviews is not None:
        config.min_reviews = args.min_reviews
    if args.filter_franchises is not None:
        config.filter_franchises = args.filter_franchises
    if args.objective is not None:
        config.objective = normalize_objective(args.objective)
    elif args.require_phone is not None or args.require_email is not None:
        require_phone = config.objective in ("phone", "both")
        require_email = config.objective in ("email", "both")
        if args.require_phone is not None:
            require_phone = args.require_phone
        if args.require_email is not None:
            require_email = args.require_email
        config.objective = objective_from_require_flags(require_phone, require_email)
    if args.require_website is not None:
        config.require_website = args.require_website
    if args.lead_enrichment is not None:
        config.lead_enrichment = args.lead_enrichment
    if args.output is not None:
        config.output_mode = args.output
    if args.json_path is not None:
        config.json_output = args.json_path
    if args.keywords is not None:
        config.keywords = args.keywords
    locations = _default_locations()
    if args.state is not None:
        state_names = set()
        for entry in args.state:
            for part in entry.split(","):
                part = part.strip().upper()
                if part:
                    state_names.add(part)
        locations = [loc for loc in locations if loc[0].upper() in state_names]
        if not locations:
            logger.warning("No states matched --state filter; using all locations")
            locations = _default_locations()
    if args.city is not None:
        city_names = set()
        for entry in args.city:
            for part in entry.split(","):
                part = part.strip()
                if part:
                    city_names.add(part.lower())
        filtered = [
            loc for loc in locations
            if loc[1].lower() in city_names
        ]
        if filtered:
            locations = filtered
        else:
            logger.warning("No cities matched --city filter; using current location set")
    if args.state is not None or args.city is not None:
        config.locations = locations
    if getattr(args, "mode", None) in ("standard", "new-business"):
        config.discovery_mode = args.mode
    if getattr(args, "max_age_days", None) is not None:
        config.nb_max_age_days = max(1, int(args.max_age_days))
    if getattr(args, "very_new_days", None) is not None:
        config.nb_very_new_days = max(1, int(args.very_new_days))
    if getattr(args, "sources", None) is not None:
        config.nb_sources = args.sources
    if getattr(args, "county", None):
        config.nb_counties = list(args.county)
    if getattr(args, "region", None):
        config.nb_region = args.region
    if getattr(args, "regions_file", None):
        config.nb_regions_file = args.regions_file
    if getattr(args, "min_new_business_score", None) is not None:
        config.nb_min_score = int(args.min_new_business_score)
    if getattr(args, "score_rules", None):
        config.nb_score_rules_path = args.score_rules
    if getattr(args, "website_check", None):
        config.nb_website_check = args.website_check
    if getattr(args, "csv_path", None):
        config.nb_csv_output = args.csv_path
    if getattr(args, "max_records_per_source", None) is not None:
        config.nb_max_records_per_source = max(1, int(args.max_records_per_source))
    config.nb_dry_run = bool(getattr(args, "dry_run", False))
    config.nb_refresh_enrichment = bool(getattr(args, "refresh_enrichment", False))
    config.nb_include_seen = bool(getattr(args, "include_seen", False))
    config.nb_headful = bool(getattr(args, "headful", False))
    config.nb_artifacts = not bool(getattr(args, "no_artifacts", False))
    if config.discovery_mode == "new-business":
        if getattr(args, "zips", None):
            from niche_search import expand_locations
            config.nb_zips = list(args.zips)
            config.locations = expand_locations(
                states=args.state,
                cities=args.city,
                zips=args.zips,
                api_key=None if config.nb_dry_run else GOOGLE_API_KEY,
            )
        if args.radius is not None:
            config.search_radius = int(args.radius)
        if args.json_path is None and config.json_output in ("leads_output.json", "", None):
            config.json_output = "new_business_leads.json"
        if config.output_mode == "csv" and config.discovery_mode != "new-business":
            config.output_mode = "json"
    elif config.output_mode == "csv":
        logger.warning("CSV output is for new-business mode. Standard mode will write JSON.")
        config.output_mode = "json"
    return config


def niche_terms(args):
    """Parsed --niche values. Empty when the flag was omitted."""
    raw = getattr(args, "niche", None)
    if not raw:
        return []
    return parse_term_list(raw)


def keyword_terms(args):
    raw = getattr(args, "keywords", None)
    if not raw:
        return []
    return parse_term_list(raw)


def _niche_search_flags_set(args):
    if getattr(args, "extra_keywords", None):
        return True
    if getattr(args, "max_leads", None) is not None:
        return True
    if getattr(args, "min_rating", None) is not None:
        return True
    if getattr(args, "zips", None):
        return True
    if getattr(args, "exclude_strong_websites", None):
        return True
    if getattr(args, "require_social", None):
        return True
    if getattr(args, "require_no_website", None):
        return True
    if getattr(args, "require_website_issue", None):
        return True
    if getattr(args, "website_requirement", None):
        return True
    if getattr(args, "radius", None) is not None:
        return True
    return False


def is_catalog_niche_search(args):
    """True when --niche should run niches.json Lead Search, not a free-text search."""
    if getattr(args, "free_text", False):
        return False
    terms = niche_terms(args)
    if not terms:
        return False
    if keyword_terms(args):
        return False
    if _niche_search_flags_set(args):
        return True
    if len(terms) != 1:
        return False
    try:
        from niche_config import NicheConfigError, get_niche
        get_niche(terms[0])
    except NicheConfigError:
        return False
    except (OSError, ImportError):
        return False
    return True


def free_text_inputs_from_args(args):
    """Return (niches, keywords) or raise EmptySearchInput when the flag is blank."""
    niches = niche_terms(args)
    keywords = keyword_terms(args)
    niche_flag = bool(getattr(args, "niche", None))
    if niche_flag and not niches:
        raise EmptySearchInput(EMPTY_NICHE_MESSAGE)
    if getattr(args, "keywords", None) is not None and not keywords and not niches:
        raise EmptySearchInput(EMPTY_SEARCH_MESSAGE)
    if getattr(args, "free_text", False) and not niches and not keywords:
        raise EmptySearchInput(EMPTY_SEARCH_MESSAGE)
    return niches, keywords


def wants_free_text(args):
    if is_catalog_niche_search(args):
        return False
    if getattr(args, "free_text", False):
        return True
    if niche_terms(args):
        return True
    if keyword_terms(args):
        return True
    if getattr(args, "keywords", None) and not keyword_terms(args):
        return True
    return False


def resolve_config(args):
    """Resolve final config from CLI flags. The script manager owns the menu."""
    if _has_cli_overrides(args):
        return config_from_args(args)
    print(
        "Pass --niche or --keywords, or run python leadgen.py with no flags to be prompted. "
        "Script Manager: python -m scripts.script_manager menu",
        file=sys.stderr,
    )
    raise SystemExit(2)


def _print_playwright_mode_banner(config):
    max_pages = config.playwright_max_pages
    print()
    print("Lead generation mode: Playwright")
    print(
        "Playwright mode uses browser-based business discovery instead of the API Manager."
    )
    print(
        "This can significantly reduce API usage and associated costs, but individual searches"
    )
    print(
        "may take longer because the browser is loading and processing search results."
    )
    print("Multi-page search is enabled.")
    print(f"Max pages per search: {max_pages}")
    print(
        f"Max results per search: {config.playwright_max_results_per_search}"
    )
    print(
        f"Area expansion: {normalize_area_expansion(config.playwright_area_expansion)}"
    )
    print()
    logger.critical(
        "Lead generation mode: Playwright (max_pages=%s, max_results_per_search=%s, expansion=%s)",
        max_pages,
        config.playwright_max_results_per_search,
        normalize_area_expansion(config.playwright_area_expansion),
    )


def _print_run_summary(stats):
    print()
    print("Lead Generation Complete")
    print(f"Mode: {stats.get('mode', '')}")
    print(f"Searches performed: {stats.get('searches_performed', 0)}")
    print(f"Searches skipped (history): {stats.get('searches_skipped', 0)}")
    print(f"Locations searched: {stats.get('locations_searched', 0)}")
    print(f"Pages processed: {stats.get('pages_processed', 0)}")
    print(f"Businesses discovered: {stats.get('businesses_discovered', 0)}")
    print(f"Duplicates removed: {stats.get('duplicates_removed', 0)}")
    print(f"Unique businesses: {stats.get('unique_businesses', 0)}")
    print(f"Businesses with websites: {stats.get('with_website', 0)}")
    print(f"Businesses without websites: {stats.get('without_website', 0)}")
    print(f"Qualified leads: {stats.get('qualified_leads', 0)}")
    if stats.get("score_55_plus") is not None:
        print(f"Score 55+: {stats.get('score_55_plus', 0)}")
        print(f"High-intent leads: {stats.get('high_intent_leads', 0)}")
        print(f"Leads with email: {stats.get('with_email', 0)}")
        print(f"Saved this run: {stats.get('saved', 0)}")
        print(f"Uploaded this run: {stats.get('uploaded', 0)}")
    print(f"API Manager calls used: {stats.get('api_manager_calls', 0)}")
    print()
    logger.critical(
        "Summary mode=%s performed=%s skipped=%s discovered=%s unique=%s "
        "qualified=%s api_calls=%s",
        stats.get("mode"),
        stats.get("searches_performed"),
        stats.get("searches_skipped"),
        stats.get("businesses_discovered"),
        stats.get("unique_businesses"),
        stats.get("qualified_leads"),
        stats.get("api_manager_calls"),
    )


def _load_contacted_emails():
    if os.path.exists(CONTACTED_FILE):
        with open(CONTACTED_FILE, "r", encoding="utf-8") as f:
            return set(line.strip().lower() for line in f if line.strip())
    return set()


def _collect_api_places(config, coords, pending, api_call_counter):
    """Nearby Search for pending keywords. Exact queries use the text before ``near``."""
    if not getattr(config, "exact_queries", False):
        places = get_places(
            coords,
            config.search_radius,
            pending,
            GOOGLE_API_KEY,
            api_call_counter=api_call_counter,
        )
        found = {
            keyword: sum(1 for place in places if place.get("niche_key") == keyword)
            for keyword in pending
        }
        return places, found
    places = []
    seen = set()
    found = {}
    for query in pending:
        short = places_keyword(query)
        batch = get_places(
            coords,
            config.search_radius,
            [short],
            GOOGLE_API_KEY,
            api_call_counter=api_call_counter,
        )
        found[query] = len(batch)
        for place in batch:
            place["niche_key"] = short
            place["search_term"] = query
            place_id = place.get("place_id")
            if place_id and place_id in seen:
                continue
            if place_id:
                seen.add(place_id)
            places.append(place)
    return places, found


def _playwright_listings(session, config, keyword, city, state, coords):
    """Maps listings for one keyword. Exact queries are searched as typed."""
    if not getattr(config, "exact_queries", False):
        return session.search_location(
            keyword,
            city,
            state,
            coords=coords,
            max_pages=config.playwright_max_pages,
            max_results=config.playwright_max_results_per_search,
            area_expansion=config.playwright_area_expansion,
        )
    from playwright_discovery import expansion_points

    short = places_keyword(keyword)
    listings = session.search_listings(
        short,
        city,
        state,
        max_pages=config.playwright_max_pages,
        max_results=config.playwright_max_results_per_search,
        query=keyword,
    )
    remaining = config.playwright_max_results_per_search - len(listings)
    for lat, lng in expansion_points(coords, config.playwright_area_expansion):
        if remaining <= 0 or session.google_blocked:
            break
        extra = session.search_listings(
            short,
            city,
            state,
            max_pages=config.playwright_max_pages,
            max_results=remaining,
            query=f"{short} near {lat:.4f},{lng:.4f}",
        )
        listings.extend(extra)
        remaining = config.playwright_max_results_per_search - len(listings)
    return listings


def gather_leads_api_manager(
    config,
    contacted_emails,
    existing_place_ids,
    api_call_counter,
    history=None,
):
    """Existing Google Places Nearby Search + Place Details discovery path."""
    history = history or SearchHistory(config.search_history_path)
    total_rows = []
    discovered = 0
    searches_performed = 0
    searches_skipped = 0
    locations_touched = set()

    log_stage(3, "Discovery", "API Manager (Google Places)")
    for state, city, coords in config.locations:
        try:
            location_keywords = keywords_for_location(config, city, state)
            if getattr(config, "exact_queries", False) and not location_keywords:
                continue
            pending, skipped = history.pending_keywords_for_location(
                location_keywords,
                city,
                state,
                leadgen_type="api_manager",
                search_radius=config.search_radius,
                skip_searched=config.skip_searched,
            )
            for prior in skipped:
                searches_skipped += 1
                log_step(
                    3,
                    1,
                    "Skip searched",
                    f"{prior.get('keyword')} × {city}, {state} "
                    f"(last completed {prior.get('completed_at')})",
                )
            if not pending:
                log_step(
                    3,
                    2,
                    "Location complete",
                    f"{city}, {state} — all keywords already in history",
                )
                continue

            locations_touched.add(f"{city}, {state}")
            log_step(
                3,
                3,
                "Location search",
                f"{city}, {state} coords={coords} keywords={len(pending)}",
            )
            places, found_counts = _collect_api_places(
                config,
                coords,
                pending,
                api_call_counter,
            )
            # Count one completed search unit per pending keyword for this location.
            for keyword in pending:
                found_for_kw = found_counts.get(keyword, 0)
                history.record_search(
                    leadgen_type="api_manager",
                    keyword=keyword,
                    city=city,
                    state=state,
                    search_radius=config.search_radius,
                    businesses_found=found_for_kw,
                    status="completed",
                )
                searches_performed += 1

            for place in places:
                place["location_searched"] = f"{city}, {state}"
                place["source"] = "api_manager"
            discovered += len(places)
            if not places:
                logger.critical(
                    "[STEP 3.4] No places found for %s, %s; moving on",
                    city,
                    state,
                )
                continue

            log_stage(4, "Qualify & analyze", f"{len(places)} businesses from {city}, {state}")
            rows = process_businesses(
                places,
                GOOGLE_API_KEY,
                existing_place_ids,
                contacted_emails,
                min_score=config.min_score,
                max_workers=config.max_workers,
                filter_franchises=config.filter_franchises,
                min_reviews=config.min_reviews,
                require_website=config.require_website,
                objective=config.objective,
                city=city,
                state=state,
                fetch_details=True,
                source="api_manager",
                api_call_counter=api_call_counter,
            )
            total_rows.extend(rows)
        except Exception as e:
            logger.error("Error processing businesses for %s, %s: %s", city, state, e)
            continue

    history.save()
    with_website = sum(1 for row in total_rows if (row.get("website") or "").strip())
    stats = {
        "mode": "API Manager",
        "searches_performed": searches_performed,
        "searches_skipped": searches_skipped,
        "locations_searched": len(locations_touched),
        "pages_processed": api_call_counter.get("places_nearby", 0),
        "businesses_discovered": discovered,
        "duplicates_removed": max(0, discovered - len({r.get("place_id") for r in total_rows})),
        "unique_businesses": len({r.get("place_id") for r in total_rows if r.get("place_id")}),
        "with_website": with_website,
        "without_website": max(0, len(total_rows) - with_website),
        "qualified_leads": len(total_rows),
        "api_manager_calls": (
            api_call_counter.get("places_nearby", 0)
            + api_call_counter.get("places_details", 0)
        ),
    }
    return total_rows, stats


def _playwright_collect_details(session, unique_stubs, config):
    """Open place panels only when the Maps card is missing required fields."""
    discovered = []
    details_needed = 0
    log_step(3, 4, "Open place panels", f"{len(unique_stubs)} listings")
    for index, stub in enumerate(unique_stubs, 1):
        if session.google_blocked:
            discovered.append(stub)
            continue
        needs_detail = listing_needs_detail(stub, config)
        if not needs_detail:
            entry = dict(stub)
            entry["source"] = stub.get("source") or "playwright"
            discovered.append(entry)
            continue
        details_needed += 1
        if details_needed == 1 or index % 10 == 0 or index == len(unique_stubs):
            log_step(
                3,
                4,
                "Detail progress",
                f"{index}/{len(unique_stubs)} {stub.get('business_name')}",
            )
        try:
            entry = session.enrich_listing(stub)
        except Exception as exc:
            logger.error(
                "[Playwright] Enrich failed for %s: %s",
                stub.get("business_name"),
                exc,
            )
            entry = dict(stub)
        entry["niche_key"] = stub.get("niche_key")
        entry["search_term"] = stub.get("search_term") or stub.get("niche_key")
        entry["location_searched"] = stub.get("location_searched")
        entry["source"] = "playwright"
        if not entry.get("place_id"):
            entry["place_id"] = extract_place_id_from_url(entry.get("profile_url"))
        discovered.append(entry)
    skipped_details = len(unique_stubs) - details_needed
    if skipped_details:
        logger.critical(
            "[STEP 3.4] Skipped %d detail pages (card already had required fields)",
            skipped_details,
        )
    return discovered


def gather_leads_playwright(
    config,
    contacted_emails,
    existing_identities,
    api_call_counter,
    history=None,
):
    """Browser-based Google Maps discovery path (no Places API calls).

    Each city/state is searched, qualified, saved, and uploaded before the next
    location starts so a later crash does not discard earlier leads.
    """
    history = history or SearchHistory(config.search_history_path)
    session = BusinessDiscoverySession()
    locations_searched = set()
    discovery_stats = {}
    duplicates_removed = 0
    searches_performed = 0
    searches_skipped = 0
    stubs_found = 0
    unique_all = []
    total_rows = []
    seen_stub_keys = set()
    saved_total = 0
    uploaded_total = 0

    log_stage(3, "Discovery", "Playwright (Google Maps)")
    try:
        for state, city, _coords in config.locations:
            loc = f"{city}, {state}"
            location_keywords = keywords_for_location(config, city, state)
            if getattr(config, "exact_queries", False) and not location_keywords:
                continue
            pending, skipped = history.pending_keywords_for_location(
                location_keywords,
                city,
                state,
                leadgen_type="playwright",
                playwright_max_pages=config.playwright_max_pages,
                playwright_area_expansion=config.playwright_area_expansion,
                skip_searched=config.skip_searched,
            )
            for prior in skipped:
                searches_skipped += 1
                log_step(
                    3,
                    1,
                    "Skip searched",
                    f"{prior.get('keyword')} × {city}, {state} "
                    f"(last completed {prior.get('completed_at')})",
                )
            if not pending:
                continue

            locations_searched.add(loc)
            city_stubs = []
            for keyword in pending:
                try:
                    log_step(3, 2, "Maps search", f"{keyword} × {city}, {state}")
                    listings = _playwright_listings(
                        session,
                        config,
                        keyword,
                        city,
                        state,
                        _coords,
                    )
                    if session.google_blocked and not listings:
                        logger.error(
                            "[Playwright] Search blocked for %s / %s, %s; not recording history",
                            keyword,
                            city,
                            state,
                        )
                        break
                    history.record_search(
                        leadgen_type="playwright",
                        keyword=keyword,
                        city=city,
                        state=state,
                        playwright_max_pages=config.playwright_max_pages,
                        playwright_area_expansion=config.playwright_area_expansion,
                        businesses_found=len(listings),
                        status="completed",
                    )
                    searches_performed += 1
                    for stub in listings:
                        entry = dict(stub)
                        if getattr(config, "exact_queries", False):
                            entry["niche_key"] = places_keyword(keyword)
                        else:
                            entry["niche_key"] = keyword
                        entry["search_term"] = keyword
                        entry["location_searched"] = loc
                        entry["source"] = "playwright"
                        if not entry.get("place_id"):
                            entry["place_id"] = extract_place_id_from_url(
                                entry.get("profile_url")
                            )
                        city_stubs.append(entry)
                except Exception as exc:
                    logger.error(
                        "[Playwright] Search failed for %s / %s, %s: %s",
                        keyword,
                        city,
                        state,
                        exc,
                    )
                    continue
                if session.google_blocked:
                    logger.error("[Playwright] Stopping remaining searches after block page")
                    break

            history.save()
            stubs_found += len(city_stubs)
            unique_stubs, loc_dupes = dedupe_businesses(city_stubs)
            kept_stubs = []
            for stub in unique_stubs:
                key = business_dedupe_key(stub)
                if key and key in seen_stub_keys:
                    loc_dupes += 1
                    continue
                if key:
                    seen_stub_keys.add(key)
                kept_stubs.append(stub)
            duplicates_removed += loc_dupes
            logger.critical(
                "[STEP 3.3] %s after discovery dedupe: %d unique (removed %d)",
                loc,
                len(kept_stubs),
                loc_dupes,
            )

            discovered = _playwright_collect_details(session, kept_stubs, config)
            unique, more_dupes = dedupe_businesses(discovered)
            duplicates_removed += more_dupes
            unique_all.extend(unique)

            try:
                log_stage(4, "Qualify & analyze", f"{loc} ({len(unique)} unique businesses)")
                rows = process_businesses(
                    unique,
                    api_key=None,
                    existing_ids=set(),
                    contacted_emails=contacted_emails,
                    min_score=config.min_score,
                    max_workers=config.max_workers,
                    filter_franchises=config.filter_franchises,
                    min_reviews=config.min_reviews,
                    require_website=config.require_website,
                    objective=config.objective,
                    city=city,
                    state=state,
                    fetch_details=False,
                    existing_identities=existing_identities,
                    source="playwright",
                    api_call_counter=api_call_counter,
                )
            except Exception as exc:
                logger.error("[Playwright] Processing failed for %s: %s", loc, exc)
                rows = []

            saved, uploaded = persist_lead_batch(rows, config, location_label=loc)
            saved_total += saved
            uploaded_total += uploaded
            total_rows.extend(rows)
            loc_web = sum(1 for item in unique if (item.get("website") or "").strip())
            loc_counts = _lead_field_counts(rows)
            print_lead_stats(
                {
                    "google_results": len(city_stubs),
                    "unique_businesses": len(unique),
                    "qualified_leads": len(rows),
                    "with_website": loc_web,
                    "without_website": max(0, len(unique) - loc_web),
                    "saved": saved,
                    "uploaded": uploaded,
                    **loc_counts,
                },
                location_label=loc,
            )
            print_lead_stats(
                {
                    "google_results": stubs_found,
                    "unique_businesses": len(unique_all),
                    "qualified_leads": len(total_rows),
                    "with_website": sum(1 for item in unique_all if (item.get("website") or "").strip()),
                    "without_website": max(
                        0,
                        len(unique_all)
                        - sum(1 for item in unique_all if (item.get("website") or "").strip()),
                    ),
                    "saved": saved_total,
                    "uploaded": uploaded_total,
                    **_lead_field_counts(total_rows),
                },
                cumulative=True,
            )
            if session.google_blocked:
                break
    finally:
        discovery_stats = dict(session.stats)
        session.close()

    with_website = sum(1 for item in unique_all if (item.get("website") or "").strip())
    counts = _lead_field_counts(total_rows)
    stats = {
        "mode": "Playwright",
        "searches_performed": searches_performed,
        "searches_skipped": searches_skipped,
        "locations_searched": len(locations_searched),
        "pages_processed": discovery_stats.get("pages_processed", 0),
        "businesses_discovered": stubs_found,
        "duplicates_removed": duplicates_removed,
        "unique_businesses": len(unique_all),
        "with_website": with_website,
        "without_website": max(0, len(unique_all) - with_website),
        "qualified_leads": len(total_rows),
        "saved": saved_total,
        "uploaded": uploaded_total,
        "flushed_incrementally": True,
        "api_manager_calls": (
            api_call_counter.get("places_nearby", 0)
            + api_call_counter.get("places_details", 0)
        ),
        **counts,
    }
    return total_rows, stats


def run_leadgen(config):
    """Run lead generation with the given configuration."""
    from datetime import datetime, timezone

    if getattr(config, "discovery_mode", "standard") == "new-business":
        from new_business_pipeline import run_new_business
        run_new_business(config)
        return

    started_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    leadgen_type = normalize_leadgen_type(config.leadgen_type)
    config.leadgen_type = leadgen_type

    log_stage(
        1,
        "Initialize",
        f"mode={leadgen_type} objective={config.objective} "
        f"skip_searched={config.skip_searched}",
    )
    if getattr(config, "exact_queries", False):
        preview = ", ".join(config.keywords[:6])
        if len(config.keywords) > 6:
            preview = f"{preview} (+{len(config.keywords) - 6} more)"
        log_step(1, 1, "Search strings", preview)
        if getattr(config, "csv_output", ""):
            log_step(
                1,
                2,
                "Output files",
                f"{config.json_output} and {config.csv_output}",
            )

    if leadgen_type == "api_manager":
        if not GOOGLE_API_KEY or GOOGLE_API_KEY == "YOUR_GOOGLE_API_KEY":
            logger.error("Please set GOOGLE_API_KEY in .env before running.")
            return
    elif leadgen_type == "playwright":
        _print_playwright_mode_banner(config)
    else:
        raise ValueError(f"Unsupported leadgen_type: {leadgen_type}")

    if config.output_mode in ("dashboard", "both") and not os.getenv("CRM_MCP_MV_LLC"):
        logger.error("CRM_MCP_MV_LLC is required for dashboard output mode.")
        return

    log_stage(2, "Load prior state")
    log_step(2, 1, "Load contacted emails", CONTACTED_FILE)
    contacted_emails = _load_contacted_emails()
    log_step(2, 2, "Contacted emails loaded", f"{len(contacted_emails)} addresses")

    log_step(2, 3, "Load existing leads", config.json_output)
    existing_place_ids = load_existing_place_ids(config.json_output)
    existing_identities = load_existing_identities(config.json_output)
    log_step(
        2,
        4,
        "Existing lead identities",
        f"{len(existing_place_ids)} place_ids / {len(existing_identities)} identity keys",
    )

    log_step(2, 5, "Load search history", config.search_history_path)
    history = SearchHistory(config.search_history_path)
    prior_searches = len(history._data.get("searches") or {})
    log_step(
        2,
        6,
        "Search history ready",
        f"{prior_searches} prior searches; skip_searched={config.skip_searched}",
    )

    api_call_counter = {"places_nearby": 0, "places_details": 0}

    if leadgen_type == "playwright":
        total_rows, stats = gather_leads_playwright(
            config,
            contacted_emails,
            existing_identities,
            api_call_counter,
            history=history,
        )
    else:
        total_rows, stats = gather_leads_api_manager(
            config,
            contacted_emails,
            existing_place_ids,
            api_call_counter,
            history=history,
        )

    if not total_rows:
        logger.critical("[STAGE] No qualifying leads found after discovery/filters.")
        log_stage(6, "Output", "skipped — nothing to save")
        log_stage(7, "Finalize")
        history.record_run({
            "started_at": started_at,
            "leadgen_type": leadgen_type,
            "stats": stats,
            "keywords": list(config.keywords),
            "locations": [f"{city}, {state}" for state, city, _ in config.locations],
        })
        history.save()
        if leadgen_type == "api_manager":
            update_usage_stats(
                nearby_calls=api_call_counter.get("places_nearby", 0),
                details_calls=api_call_counter.get("places_details", 0),
            )
        _print_run_summary(stats)
        return

    logger.critical(
        "[STAGE 4 complete] Found %d qualifying leads (min score %d)",
        len(total_rows),
        config.min_score,
    )

    if config.lead_enrichment:
        enriched = enrich_missing_emails(total_rows, leadgen_type=leadgen_type)
        if enriched and contacted_emails:
            kept = [row for row in total_rows if not _is_contacted(row, contacted_emails)]
            if len(kept) != len(total_rows):
                log_step(
                    5,
                    3,
                    "Drop contacted after enrichment",
                    f"{len(total_rows) - len(kept)} leads already in {CONTACTED_FILE}",
                )
                total_rows = kept
        stats["qualified_leads"] = len(total_rows)
    else:
        log_stage(5, "Lead enrichment", "skipped by configuration")

    log_stage(6, "Output", config.output_mode)
    flushed = bool(stats.get("flushed_incrementally"))
    csv_path = getattr(config, "csv_output", "") or None
    if flushed and not config.lead_enrichment:
        log_step(6, 1, "Incremental output", "already saved/uploaded after each location")
    else:
        if config.output_mode in ("json", "both") or csv_path:
            detail = config.json_output
            if csv_path:
                detail = f"{config.json_output} and {csv_path}"
            log_step(6, 1, "Save leads", detail)
            save_results(total_rows, config.json_output, csv_path=csv_path)
            stats["saved"] = len(total_rows)
        if config.output_mode in ("dashboard", "both"):
            log_step(6, 2, "Dashboard bulk ingest", f"{len(total_rows)} leads")
            stats["uploaded"] = send_to_dashboard(total_rows) or 0

    log_stage(7, "Finalize")
    history.record_run({
        "started_at": started_at,
        "leadgen_type": leadgen_type,
        "stats": stats,
        "keywords": list(config.keywords),
        "locations": [f"{city}, {state}" for state, city, _ in config.locations],
        "qualified_leads": len(total_rows),
    })
    history.save()
    log_step(7, 1, "Search history updated", config.search_history_path)

    if leadgen_type == "api_manager":
        usage = update_usage_stats(
            nearby_calls=api_call_counter.get("places_nearby", 0),
            details_calls=api_call_counter.get("places_details", 0),
        )
        log_step(
            7,
            2,
            "API usage updated",
            f"{DEFAULT_USAGE_PATH} total_calls={usage.get('total_calls')}",
        )

    _print_run_summary(stats)


def main():
    args = parse_args()
    if getattr(args, "list_sources", False):
        from new_business_sources import list_sources
        for line in list_sources():
            print(line)
        return
    if getattr(args, "review_leads", False):
        from niche_results import review_leads
        review_leads(json_path=args.json_path or "niche_leads_output.json")
        return
    if is_catalog_niche_search(args):
        from niche_search import (
            config_from_leadgen,
            expand_locations,
            run_niche_search,
        )
        base = config_from_args(args)
        locations = expand_locations(
            states=args.state,
            cities=args.city,
            zips=getattr(args, "zips", None),
            api_key=GOOGLE_API_KEY,
        )
        niche_config = config_from_leadgen(
            base,
            niche_terms(args)[0],
            extra={
                "locations": locations,
                "extra_keywords": args.extra_keywords or [],
                "search_radius": args.radius if args.radius is not None else base.search_radius,
                "max_leads": args.max_leads or 0,
                "min_reviews": args.min_reviews if args.min_reviews is not None else None,
                "min_rating": args.min_rating or 0,
                "min_score": args.min_score if args.min_score is not None else None,
                "filter_franchises": (
                    args.filter_franchises
                    if args.filter_franchises is not None
                    else base.filter_franchises
                ),
                "exclude_strong_websites": bool(args.exclude_strong_websites),
                "require_phone": bool(args.require_phone),
                "require_email": bool(args.require_email),
                "require_social": bool(args.require_social),
                "require_no_website": bool(args.require_no_website),
                "require_website_issue": bool(args.require_website_issue),
                "require_active_business": (
                    True
                    if args.require_active_business is None
                    else bool(args.require_active_business)
                ),
                "website_requirement": args.website_requirement or (
                    "weak_or_none" if args.exclude_strong_websites else "any"
                ),
                "json_output": args.json_path or "niche_leads_output.json",
                "open_reviewer": False,
            },
        )
        run_niche_search(niche_config)
        return
    if not _has_cli_overrides(args):
        config = interactive_free_text_run()
        if config is None:
            print("Exiting.")
            return
        run_leadgen(config)
        return
    config = resolve_config(args)
    if config is None:
        print("Exiting.")
        return
    if wants_free_text(args):
        try:
            niches, keywords = free_text_inputs_from_args(args)
            apply_free_text_search(
                config,
                niches,
                keywords,
                explicit_json=args.json_path is not None,
            )
        except EmptySearchInput as exc:
            print(exc, file=sys.stderr)
            raise SystemExit(2)
    run_leadgen(config)
