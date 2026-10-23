"""places_api implementation for leadgen.

Executed into the leadgen module so imports and patches of leadgen.*
keep resolving there. This file is not an import target.
"""

def get_places(location, radius, keywords, api_key, api_call_counter=None):
    """Use Nearby Search to gather place_ids for given keywords and location."""
    base = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    places = {}
    for kw in keywords:
        logger.critical("Searching for keyword '%s' around location %s", kw, location)
        params = {
            "location": location,
            "radius": radius,
            "keyword": kw,
            "key": api_key,
        }
        url = base
        while True:
            try:
                r = requests.get(url, params=params, timeout=10)
                if api_call_counter is not None:
                    api_call_counter["places_nearby"] = (
                        api_call_counter.get("places_nearby", 0) + 1
                    )
                data = r.json()

                logger.info("HTTP Status Code: %s", r.status_code)
                logger.info("Places Status: %s", data.get("status"))
                logger.info("Error Message: %s", data.get("error_message"))
                logger.info("Results Count: %d", len(data.get("results", [])))

            except Exception as e:
                logger.error("Nearby search failed for keyword %s: %s", kw, e)
                break
            data = r.json()
            results = data.get("results", [])
            for p in results:
                pid = p.get("place_id")
                if not pid:
                    continue
                if pid in places:
                    continue
                places[pid] = {
                    "business_name": p.get("name"),
                    "place_id": pid,
                    "rating": p.get("rating"),
                    "user_ratings_total": p.get("user_ratings_total"),
                    "address": p.get("vicinity") or p.get("formatted_address"),
                    "niche_key": kw,
                    "search_term": kw,
                    "source": "api_manager",
                }
            next_token = data.get("next_page_token")
            if next_token:
                time.sleep(PLACES_SLEEP)
                params = {"pagetoken": next_token, "key": api_key}
                continue
            break
    logger.info("Collected %d unique places", len(places))
    return list(places.values())


def get_place_details(place_id, api_key):
    """Fetch Place Details for a single place_id."""
    base = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {
        "place_id": place_id,
        "fields": (
            "website,formatted_phone_number,formatted_address,name,place_id,"
            "business_status,reviews,rating,user_ratings_total"
        ),
        "reviews_sort": "newest",
        "key": api_key,
    }
    empty = {
        "website": None,
        "phone_google": None,
        "address": None,
        "business_status": None,
        "reviews": [],
        "rating": None,
        "user_ratings_total": None,
    }
    try:
        r = requests.get(base, params=params, timeout=10)
        data = r.json()
        result = data.get("result", {})
        return {
            "website": result.get("website"),
            "phone_google": result.get("formatted_phone_number"),
            "address": result.get("formatted_address"),
            "business_status": result.get("business_status"),
            "reviews": result.get("reviews") or [],
            "rating": result.get("rating"),
            "user_ratings_total": result.get("user_ratings_total"),
        }
    except Exception as e:
        logger.error("Place details failed for %s: %s", place_id, e)
        return dict(empty)


