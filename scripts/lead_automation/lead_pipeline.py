"""lead_pipeline implementation for leadgen.

Executed into the leadgen module so imports and patches of leadgen.*
keep resolving there. This file is not an import target.
"""

def process_businesses(
    businesses,
    api_key,
    existing_ids,
    contacted_emails,
    min_score=80,
    max_workers=12,
    filter_franchises=True,
    min_reviews=5,
    require_website=False,
    objective="phone",
    city=None,
    state=None,
    fetch_details=True,
    existing_identities=None,
    source="api_manager",
    api_call_counter=None,
):
    """Given list of basic business entries, enrich with place details and analyze websites concurrently.

    When fetch_details is False (Playwright path), Place Details API calls are skipped and
    fields already present on each business entry are used instead.
    """
    objective = normalize_objective(objective)
    enriched = []
    quality_rejects = {}
    if fetch_details:
        log_step(4, 2, "Fetch Place Details", f"{len(businesses)} businesses")
        logger.critical("Fetching place details for %d businesses", len(businesses))
    else:
        log_step(4, 2, "Use discovered fields", "Place Details API skipped")
        logger.critical(
            "Processing %d discovered businesses (Place Details API skipped)",
            len(businesses),
        )
    for b in businesses:
        place_id = b.get("place_id")
        if fetch_details:
            details = get_place_details(place_id, api_key)
            if api_call_counter is not None:
                api_call_counter["places_details"] = (
                    api_call_counter.get("places_details", 0) + 1
                )
            time.sleep(PLACES_SLEEP)
            entry = {
                "business_name": b.get("business_name"),
                "place_id": place_id,
                "address": details.get("address") or b.get("address"),
                "phone_google": details.get("phone_google"),
                "website": details.get("website"),
                "rating": details.get("rating") if details.get("rating") is not None else b.get("rating"),
                "user_ratings_total": (
                    details.get("user_ratings_total")
                    if details.get("user_ratings_total") is not None
                    else b.get("user_ratings_total")
                ),
                "business_status": details.get("business_status"),
                "reviews": details.get("reviews") or [],
                "niche_key": b.get("niche_key"),
                "profile_url": b.get("profile_url"),
                "source": b.get("source") or source,
                "search_term": b.get("search_term") or b.get("niche_key"),
                "location_searched": b.get("location_searched"),
            }
        else:
            entry = {
                "business_name": b.get("business_name"),
                "place_id": place_id,
                "address": b.get("address"),
                "phone_google": b.get("phone_google"),
                "website": b.get("website"),
                "rating": b.get("rating"),
                "user_ratings_total": b.get("user_ratings_total"),
                "business_status": b.get("business_status"),
                "reviews": b.get("reviews") or [],
                "niche_key": b.get("niche_key"),
                "profile_url": b.get("profile_url"),
                "source": b.get("source") or source,
                "search_term": b.get("search_term") or b.get("niche_key"),
                "location_searched": b.get("location_searched"),
                "category": b.get("category"),
            }
        if not entry.get("address"):
            logger.info(
                "No address from Places for %s (%s)",
                entry.get("business_name"),
                place_id,
            )
        ok, reason = passes_quality_filters(
            entry,
            filter_franchises=filter_franchises,
            min_reviews=min_reviews,
            require_phone=(objective == "phone"),
            require_website=require_website,
        )
        if not ok:
            quality_rejects[reason] = quality_rejects.get(reason, 0) + 1
            continue
        enriched.append(entry)

    if quality_rejects:
        for reason, count in sorted(quality_rejects.items()):
            logger.info("Quality filter rejected %d leads: %s", count, reason)

    unique = {}
    for e in enriched:
        key = business_dedupe_key(e) or (e.get("website") or e.get("business_name"),)
        if key in unique:
            continue
        unique[key] = e
    businesses_unique = list(unique.values())
    log_step(
        4,
        3,
        "After quality filters + dedupe",
        f"{len(businesses_unique)} businesses remain",
    )
    logger.critical("After deduplication: %d businesses", len(businesses_unique))

    analyses = {}
    with_website = sum(1 for b in businesses_unique if (b.get("website") or "").strip())
    log_step(
        4,
        4,
        "Website analysis",
        f"{with_website} with website / {len(businesses_unique) - with_website} without",
    )
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        future_map = {}
        for b in businesses_unique:
            url = b.get("website")
            if url:
                future = ex.submit(analyze_website, url)
            else:
                future = ex.submit(
                    lambda: {
                        "emails": [],
                        "phones_website": [],
                        "https": False,
                        "has_viewport": False,
                        "html_length": 0,
                        "has_title": False,
                        "has_cta": False,
                        "error": None,
                    }
                )
            future_map[future] = b
        for fut in as_completed(future_map):
            b = future_map[fut]
            analysis_key = b.get("place_id") or business_dedupe_key(b) or id(b)
            try:
                analyses[analysis_key] = fut.result()
            except Exception as e:
                logger.error("Website analysis failed for %s: %s", b.get("website"), e)
                analyses[analysis_key] = {
                    "emails": [],
                    "phones_website": [],
                    "https": False,
                    "has_viewport": False,
                    "html_length": 0,
                    "has_title": False,
                    "has_cta": False,
                    "error": str(e),
                }

    rows = []
    filtered_below_min = 0
    filtered_objective = 0
    session = EmailDiscoverySession() if objective != "phone" else None
    if session is not None:
        log_step(4, 5, "Email discovery", f"objective={objective}")
    else:
        log_step(4, 5, "Email discovery", "skipped (objective=phone)")
    try:
        for b in businesses_unique:
            place_id = b.get("place_id")
            if existing_identities is not None:
                if not is_new_identity(b, existing_identities):
                    continue
            else:
                if not place_id:
                    continue
                if not is_new_place(place_id, existing_ids):
                    continue

            analysis_key = place_id or business_dedupe_key(b) or id(b)
            a = analyses.get(analysis_key, {})
            emails = a.get("emails") or []
            emails_clean = []
            seen_emails = set()
            for raw in emails:
                email = validate_email(raw)
                if email and email not in seen_emails:
                    seen_emails.add(email)
                    emails_clean.append(email)

            row = {
                "business_name": b.get("business_name"),
                "place_id": place_id,
                "address": b.get("address") or "",
                "phone_google": b.get("phone_google"),
                "phone_website": ";".join(a.get("phones_website", [])) if a.get("phones_website") else None,
                "email": ";".join(emails_clean),
                "has_email": bool(emails_clean),
                "website": b.get("website"),
                "rating": b.get("rating"),
                "user_ratings_total": b.get("user_ratings_total"),
                "business_status": b.get("business_status"),
                "https": a.get("https", False),
                "has_viewport": a.get("has_viewport", False),
                "html_length": a.get("html_length", 0),
                "has_cta": a.get("has_cta", False),
                "niche_key": b.get("niche_key"),
                "profile_url": b.get("profile_url"),
                "source": b.get("source") or source,
                "search_term": b.get("search_term") or b.get("niche_key"),
                "location_searched": b.get("location_searched"),
            }
            if emails_clean:
                row["email_source"] = "website"

            if session is not None and should_run_email_discovery(row, objective):
                logger.info("[EMAIL] Processing: %s", row.get("business_name"))
                if not emails_clean:
                    logger.info("[EMAIL] No email found in primary source")
                try:
                    enrich_lead_with_email(row, city=city, state=state, session=session)
                except Exception as e:
                    logger.error("[EMAIL] Enrichment failed for %s: %s", row.get("business_name"), e)

            emails_clean = lead_emails(row)
            row["email"] = ";".join(emails_clean)
            row["has_email"] = bool(emails_clean)

            if any(email in contacted_emails for email in emails_clean):
                continue

            has_website = bool(row.get("website"))
            lead_score = score_lead(
                has_website,
                row.get("https", False),
                row.get("has_viewport", False),
                row.get("html_length", 0),
                row.get("has_email"),
                row.get("has_cta", False),
                row.get("rating"),
                row.get("user_ratings_total"),
                row.get("business_status"),
            )
            logger.info("[SCORE] Lead score: %s", lead_score)
            row["lead_score"] = lead_score

            if lead_score < min_score:
                filtered_below_min += 1
                continue

            if not lead_meets_objective(row, objective):
                logger.info("[OBJECTIVE] %s -> FAIL", objective)
                logger.info("[LEAD] Rejected")
                filtered_objective += 1
                continue

            logger.info("[OBJECTIVE] %s -> PASS", objective)
            logger.info("[LEAD] Qualified")

            owner_names = extract_owner_names(b.get("reviews") or [])
            row["owner_names"] = ";".join(owner_names) if owner_names else None
            row.pop("has_cta", None)
            rows.append(row)
    finally:
        if session is not None:
            session.close()

    if filtered_objective:
        logger.info("Filtered %d leads that failed objective %s", filtered_objective, objective)
    if filtered_below_min:
        logger.info(
            "Filtered %d leads below minimum score %d",
            filtered_below_min,
            min_score,
        )
    return rows



def enrich_missing_emails(rows, leadgen_type=None):
    """Fill in missing emails / research leads; returns rows the enricher processed.

    API Manager discovery uses Facebook/Apify (leadenrich.py). Playwright discovery
    uses Google research (leadenrich_playwright.py). Both modules import leadgen
    lazily for dashboard ingest, so they are imported here rather than at module
    level. Enrichment is best effort: a failure must not cost the run its leads.
    """
    provider = normalize_leadgen_type(leadgen_type or DEFAULT_LEADGEN_TYPE)
    log_stage(5, "Lead enrichment", f"{len(rows)} qualifying leads ({provider})")
    try:
        if provider == "playwright":
            from leadenrich_playwright import EnrichConfig, enrich_leads

            log_step(5, 1, "Hand off to Playwright Google enrichment")
        else:
            from leadenrich import EnrichConfig, enrich_leads

            log_step(5, 1, "Hand off to Facebook enrichment")
        enriched = enrich_leads(rows, EnrichConfig())
    except Exception as e:
        logger.error("[STAGE 5] Lead enrichment failed: %s", e)
        return []

    if enriched:
        logger.critical(
            "[STEP 5.2] Enrichment updated %d leads",
            len(enriched),
        )
    else:
        log_step(5, 2, "Enrichment complete", "no new emails found")
    return enriched


