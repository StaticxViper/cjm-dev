"""lead_scoring implementation for leadgen.

Executed into the leadgen module so imports and patches of leadgen.*
keep resolving there. This file is not an import target.
"""

def latest_review_timestamp(reviews):
    """Return the newest review unix timestamp, or None if no reviews."""
    if not reviews:
        return None
    times = [r.get("time") for r in reviews if r.get("time") is not None]
    return max(times) if times else None


def is_review_stale(latest_ts, months=REVIEW_MAX_AGE_MONTHS):
    """Return True if latest review is older than the given number of months."""
    if latest_ts is None:
        return False
    latest_dt = datetime.fromtimestamp(latest_ts, tz=timezone.utc)
    cutoff = datetime.now(timezone.utc) - timedelta(days=months * 30)
    return latest_dt < cutoff


def is_franchise(business_name, website, franchise_data=None):
    """Return True if business name or website matches known franchise lists."""
    data = franchise_data if franchise_data is not None else FRANCHISE_DATA
    name = (business_name or "").lower()
    for franchise_name in data.get("names") or []:
        if franchise_name and franchise_name.lower() in name:
            return True

    if website:
        try:
            host = urlparse(website if "://" in website else f"http://{website}").hostname or ""
            host = host.lower().removeprefix("www.")
            for domain in data.get("domains") or []:
                domain = (domain or "").lower().removeprefix("www.")
                if domain and (host == domain or host.endswith("." + domain)):
                    return True
        except Exception:
            pass
    return False


def extract_owner_names(reviews, max_names=5):
    """Extract likely owner/decision-maker names from review text."""
    if not reviews:
        return []
    found = []
    seen = set()
    for review in reviews:
        text = review.get("text") or ""
        if not text:
            continue
        for pattern in OWNER_NAME_PATTERNS:
            for match in pattern.finditer(text):
                name = " ".join(part.capitalize() for part in match.group(1).split())
                key = name.lower()
                first = key.split()[0]
                if first in OWNER_NAME_FALSE_POSITIVES or key in seen:
                    continue
                seen.add(key)
                found.append(name)
                if len(found) >= max_names:
                    return found
    return found


def passes_quality_filters(
    entry,
    filter_franchises=True,
    min_reviews=5,
    franchise_data=None,
    require_phone=True,
    require_website=False,
):
    """Return (passed, reason) for hard quality filters before website scraping."""
    status = entry.get("business_status")
    if status in CLOSED_STATUSES:
        return False, "closed_business"

    if filter_franchises and is_franchise(
        entry.get("business_name"),
        entry.get("website"),
        franchise_data=franchise_data,
    ):
        return False, "franchise"

    try:
        count = int(entry.get("user_ratings_total") or 0)
    except (TypeError, ValueError):
        count = 0
    if count < min_reviews:
        return False, "low_review_count"

    if require_phone and not is_valid_us_phone(entry.get("phone_google")):
        return False, "invalid_phone"

    if require_website and not (entry.get("website") or "").strip():
        return False, "no_website"

    reviews = entry.get("reviews") or []
    if reviews:
        latest = latest_review_timestamp(reviews)
        if latest is not None and is_review_stale(latest):
            return False, "stale_reviews"

    return True, ""


def _extract_emails_from_html(html, soup=None):
    """Return sorted unique emails found in HTML, filtering junk and false positives."""
    return extract_emails_from_html(html, soup=soup)


def _extract_phones_from_html(html):
    """Return sorted unique US-format phones found in HTML."""
    phone_matches = re.findall(
        r"(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}",
        html or "",
    )
    cleaned_phones = set()
    for p in phone_matches:
        digits = re.sub(r"[^0-9]", "", p)
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if len(digits) == 10:
            cleaned_phones.add(
                "(+1) {}-{}-{}".format(digits[0:3], digits[3:6], digits[6:10])
            )
    return sorted(cleaned_phones)


def _fetch_html(url):
    """GET url and return response text, or raise."""
    r = requests_get(
        url,
        timeout=10,
        headers=FETCH_HEADERS,
        allow_redirects=True,
        getter=requests.get,
    )
    return r.text or ""


def _normalize_website_url(url):
    """Normalize scheme for scraping; prefer https for bare hosts."""
    return ensure_http_url(url)


def _https_upgrade_url(url):
    """Return an https:// variant of an http:// URL, or None if not applicable."""
    parsed = urlparse(url)
    if parsed.scheme.lower() != "http":
        return None
    return parsed._replace(scheme="https").geturl()


def analyze_website(url):
    """Fetch a website and extract emails, phones, https status, viewport, and basic quality signals.

    If the homepage has no emails, also tries common contact/about paths on the same origin.
    """
    result = {
        "emails": [],
        "phones_website": [],
        "https": False,
        "has_viewport": False,
        "html_length": 0,
        "has_title": False,
        "has_cta": False,
        "error": None,
    }
    if not url:
        return result

    url = _normalize_website_url(url)
    result["https"] = url.lower().startswith("https://")

    try:
        html = _fetch_html(url)
        if len(html) < MIN_USEFUL_HTML_LENGTH:
            https_url = _https_upgrade_url(url)
            if https_url:
                try:
                    https_html = _fetch_html(https_url)
                    if len(https_html) > len(html):
                        html = https_html
                        url = https_url
                        result["https"] = True
                except Exception:
                    pass
    except Exception as e:
        https_url = _https_upgrade_url(url)
        if https_url:
            try:
                html = _fetch_html(https_url)
                url = https_url
                result["https"] = True
            except Exception as e2:
                result["error"] = str(e2)
                return result
        else:
            result["error"] = str(e)
            return result

    result["html_length"] = len(html)
    soup = BeautifulSoup(html, "html.parser")
    result["has_title"] = has_title_tag(soup)
    result["has_viewport"] = has_viewport(soup)

    emails = set(_extract_emails_from_html(html, soup=soup))
    phones = set(_extract_phones_from_html(html))

    text = soup.get_text(separator=" ").lower()
    result["has_cta"] = text_has_keywords(text, ("call", "contact", "quote", "estimate"))

    if not emails:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        for path in CONTACT_PAGE_PATHS:
            page_url = urljoin(base + "/", path.lstrip("/"))
            try:
                page_html = _fetch_html(page_url)
            except Exception:
                continue
            page_soup = BeautifulSoup(page_html, "html.parser")
            emails.update(_extract_emails_from_html(page_html, soup=page_soup))
            phones.update(_extract_phones_from_html(page_html))
            if emails:
                break

    result["emails"] = sorted(emails)
    result["phones_website"] = sorted(phones)
    return result


def score_lead(
    has_website,
    https,
    has_viewport,
    html_length,
    has_email,
    has_cta,
    rating,
    user_ratings_total,
    business_status=None,
):
    """Return integer lead_score 0-100 (higher = worse digital presence / better outreach target)."""
    w = SCORE_WEIGHTS
    raw = 0
    max_possible = w["low_rating"] + w["low_reviews"] + w["has_email"] + w["unknown_status"]

    if not has_website:
        max_possible += w["no_website"]
        raw += w["no_website"]
    else:
        max_possible += w["no_https"] + w["no_viewport"] + w["short_html"] + w["no_cta"]
        if not https:
            raw += w["no_https"]
        if not has_viewport:
            raw += w["no_viewport"]
        try:
            if html_length < 5000:
                raw += w["short_html"]
        except Exception:
            raw += w["short_html"]
        if not has_cta:
            raw += w["no_cta"]

    if has_email:
        raw += w["has_email"]
    if not business_status:
        raw += w["unknown_status"]

    try:
        if rating is None or float(rating) < 4.5:
            raw += w["low_rating"]
    except Exception:
        raw += w["low_rating"]
    try:
        if user_ratings_total is None or int(user_ratings_total) < 15:
            raw += w["low_reviews"]
    except Exception:
        raw += w["low_reviews"]

    if not max_possible:
        return 0
    return round(raw / max_possible * 100)


