"""lead_persistence implementation for leadgen.

Executed into the leadgen module so imports and patches of leadgen.*
keep resolving there. This file is not an import target.
"""
import csv
from pathlib import Path

LEAD_CSV_FIELDS = (
    "business_name",
    "place_id",
    "address",
    "phone_google",
    "phone_website",
    "email",
    "website",
    "rating",
    "user_ratings_total",
    "business_status",
    "lead_score",
    "niche_key",
    "search_term",
    "location_searched",
    "source",
    "profile_url",
    "owner_names",
)


def save_lead_csv(rows, csv_path):
    """Write the current lead set to CSV. Caller picks a path that is not an older file."""
    path = Path(csv_path)
    if str(path.parent) not in ("", "."):
        path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(LEAD_CSV_FIELDS), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                key: "" if row.get(key) is None else row.get(key)
                for key in LEAD_CSV_FIELDS
            })
    logger.critical("Saved %d leads to %s", len(rows), path)


def save_results(rows, json_path, csv_path=None):
    """Append lead rows to a JSON array file, deduping by place_id (or website+name)."""
    existing = []
    if os.path.exists(json_path):
        try:
            with open(json_path, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, list):
                existing = loaded
        except (OSError, json.JSONDecodeError) as e:
            logger.error("Failed to read existing leads from %s: %s", json_path, e)
            existing = []

    combined = list(existing) + list(rows)
    seen_place_ids = set()
    seen_fallback = set()
    deduped = []
    for row in combined:
        place_id = row.get("place_id")
        if place_id:
            if place_id in seen_place_ids:
                continue
            seen_place_ids.add(place_id)
        else:
            key = (row.get("website") or "", row.get("business_name") or "")
            if key in seen_fallback:
                continue
            seen_fallback.add(key)
        deduped.append(row)

    def _score_key(row):
        try:
            return -int(row.get("lead_score") or 0)
        except (TypeError, ValueError):
            return 0

    deduped.sort(key=_score_key)
    json_file = Path(json_path)
    if str(json_file.parent) not in ("", "."):
        json_file.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(deduped, f, indent=2)
        f.write("\n")
    if existing:
        logger.info("Appended and saved %d total leads to %s", len(deduped), json_path)
    else:
        logger.critical("Saved %d leads to %s", len(deduped), json_path)
    if csv_path:
        save_lead_csv(deduped, csv_path)


def extract_real_email(raw_email_field):
    emails = (raw_email_field or "").split(";")
    for e in emails:
        e = e.strip().lower()
        if e and "sentry" not in e and "wixpress" not in e:
            return e
    return ""


def send_to_dashboard(rows):
    """Create qualifying leads in the CRM via the MCP server."""
    from crm_mcp import CrmMcpClient

    payload = []
    for row in rows:
        niche_key = row.get("niche_key")
        category = row.get("category") or KEYWORD_CATEGORIES.get(niche_key, niche_key)
        tags = [
            "lead_automation",
            "playwright" if (row.get("source") == "playwright") else "google-places-api",
        ]
        for extra in row.get("tags") or []:
            if extra and extra not in tags:
                tags.append(extra)
        score = row.get("lead_score")
        if score in (None, ""):
            score = row.get("new_business_score")
        item = {
            "business_name": row["business_name"],
            "address": row.get("address") or "",
            "phone": row.get("phone_google") or row.get("phone") or "",
            "email": extract_real_email(row.get("email") or ""),
            "category": category,
            "tags": tags,
            "score": int(score or 0),
        }
        if row.get("website") not in (None, ""):
            item["website"] = row.get("website")
        if row.get("rating") not in (None, ""):
            item["rating"] = row.get("rating")
        if row.get("user_ratings_total") not in (None, ""):
            item["user_ratings_total"] = row.get("user_ratings_total")
        if row.get("niche"):
            item["niche"] = row.get("niche")
        payload.append(item)

    if not payload:
        logger.info("No leads to send to CRM")
        return 0

    client = CrmMcpClient()
    if not client.api_key:
        logger.error("CRM_MCP_MV_LLC is required to upload leads.")
        return 0

    logger.critical("Sending %d leads to CRM", len(payload))
    uploaded = 0
    for item in payload:
        last_error = None
        for attempt in range(1, 4):
            try:
                client.create_lead(item)
                uploaded += 1
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                logger.error(
                    "CRM upload attempt %d/3 failed for %s: %s",
                    attempt,
                    item.get("business_name"),
                    exc,
                )
                if attempt < 3:
                    time.sleep(1.5 * attempt)
        if last_error:
            logger.error(
                "CRM upload skipped for %s; the lead remains in JSON: %s",
                item.get("business_name"),
                last_error,
            )
    if uploaded != len(payload):
        logger.error(
            "CRM upload finished with %d of %d leads created",
            uploaded,
            len(payload),
        )
    return uploaded


def persist_lead_batch(rows, config, location_label=None, json_path=None):
    """Save and/or upload one location batch. Returns (saved, uploaded)."""
    saved = 0
    uploaded = 0
    if not rows:
        return saved, uploaded
    path = json_path or getattr(config, "json_output", None) or "leads_output.json"
    mode = getattr(config, "output_mode", "json")
    csv_path = getattr(config, "csv_output", "") or None
    if mode in ("json", "both") or csv_path:
        save_results(rows, path, csv_path=csv_path)
        saved = len(rows)
        if location_label:
            logger.critical("Saved %d leads after %s -> %s", saved, location_label, path)
    if mode in ("dashboard", "both"):
        try:
            uploaded = send_to_dashboard(rows) or 0
        except Exception as exc:
            logger.error(
                "Dashboard ingest failed after %s: %s",
                location_label or "batch",
                exc,
            )
            uploaded = 0
        if location_label:
            if uploaded:
                logger.critical("Uploaded %d leads after %s", uploaded, location_label)
            else:
                logger.error(
                    "Dashboard ingest missed after %s; JSON still has %d leads",
                    location_label,
                    saved,
                )
    return saved, uploaded


def _lead_field_counts(rows):
    with_email = 0
    high_pri = 0
    score_55 = 0
    high_intent = 0
    for row in rows or []:
        email = str(row.get("email") or "")
        if "@" in email:
            with_email += 1
        tags = row.get("tags") or []
        if "high-pri-lead" in tags or row.get("high_pri_lead"):
            high_pri += 1
        try:
            score = int(row.get("lead_score") or 0)
        except (TypeError, ValueError):
            score = 0
        if score >= 55:
            score_55 += 1
        if score >= 70:
            high_intent += 1
    return {
        "with_email": with_email,
        "high_pri": high_pri,
        "score_55_plus": score_55,
        "high_intent_leads": high_intent,
    }


def print_lead_stats(stats, location_label=None, cumulative=False):
    heading = "Lead stats (run)" if cumulative else "Lead stats"
    if location_label:
        heading = f"{heading} — {location_label}"
    log_step(
        4,
        1,
        heading,
        (
            f"raw {stats.get('google_results', stats.get('businesses_discovered', 0))} | "
            f"unique {stats.get('unique_businesses', 0)} | "
            f"qualified {stats.get('qualified_leads', 0)} | "
            f"55+ {stats.get('score_55_plus', 0)} | "
            f"high-intent {stats.get('high_intent_leads', 0)} | "
            f"websites {stats.get('with_website', 0)}/{stats.get('without_website', 0)} | "
            f"emails {stats.get('with_email', 0)} | "
            f"high-pri {stats.get('high_pri', 0)} | "
            f"saved {stats.get('saved', 0)} | uploaded {stats.get('uploaded', 0)}"
        ),
    )


