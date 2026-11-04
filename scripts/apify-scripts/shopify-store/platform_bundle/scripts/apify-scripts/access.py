"""Cheapest-path proxy and CAPTCHA gate for Apify Actors.

Direct request first. Apify Proxy only after a real block. A CAPTCHA solve
only when that proxy retry is still a challenge, allowCaptcha is true, and
the spend cap covers it. Amounts are cents so a cap check does not drift.
A charge is recorded only after the request was sent or a solver returned a
token. Robots disallow is not a block and is not retried through a proxy.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import logging
import os
import uuid
from urllib.parse import quote, unquote, urlparse

log = logging.getLogger("apify")

PROXY_EVENT = "proxy"
CAPTCHA_EVENT = "captcha"
DEFAULT_PROXY_GROUP = "DATACENTER"
DEFAULT_PRICES_USD = {
    "proxy": 0.01,
    "captcha": 1.00,
}

# Strong challenge markers. A page that merely says "captcha" in prose is
# not treated as a wall. Google sorry pages are included so a Maps block can
# reach the allowCaptcha gate.
CHALLENGE_MARKERS = (
    "cf-browser-verification",
    "cf-challenge",
    "challenge-platform",
    "/cdn-cgi/challenge",
    "just a moment",
    "attention required",
    "turnstile",
    "hcaptcha",
    "g-recaptcha",
    "recaptcha",
    "data-sitekey",
    "/sorry/",
    "google.com/sorry",
    "unusual traffic",
    "detected unusual traffic",
    "our systems have detected",
)

STOP_MESSAGES = {
    "budget": "Blocked. The spend cap was reached before a proxy or CAPTCHA retry.",
    "proxy_unavailable": "Blocked. The direct request was rejected and Apify Proxy is not configured.",
    "captcha_disabled": "Blocked by a challenge. CAPTCHA solving is off for this run.",
    "captcha_unavailable": "Blocked by a challenge. No CAPTCHA solver is configured, so nothing was billed for a solve.",
    "challenge": "Blocked. The proxy retry was still rejected.",
}

_NOT_BLOCKS = frozenset({"robots_disallowed", "request_cap", "proxy_unavailable"})


def to_cents(usd):
    return int(round(float(usd) * 100 + 1e-9))


def stop_message(stop):
    return STOP_MESSAGES.get(stop) or STOP_MESSAGES["challenge"]


def _bounded_float(value, default, low, high):
    if value is None or value == "":
        number = default
    else:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = default
    if number < low:
        number = low
    if number > high:
        number = high
    return number


def _flag(value, default):
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _proxy_configuration_dict(raw):
    config = (raw or {}).get("proxyConfiguration")
    if isinstance(config, dict):
        return config
    return {}


def _proxy_groups(raw):
    config = _proxy_configuration_dict(raw)
    groups = config.get("apifyProxyGroups")
    if not groups:
        groups = (raw or {}).get("proxyGroups") or []
    if isinstance(groups, str):
        groups = [part.strip() for part in groups.split(",") if part.strip()]
    cleaned = []
    if isinstance(groups, list):
        for item in groups:
            text = str(item or "").strip()
            if text and text not in cleaned:
                cleaned.append(text)
    return cleaned


def read_access_settings(raw, prices_usd=None):
    """Parse spend caps, allowCaptcha, and the proxy group from Actor input.

    maxProxyCostUsd is clamped to maxSpendUsd. An empty proxy group means
    datacenter when a later block escalates. Prices default to the shared
    proxy and CAPTCHA events; callers pass their result price as well.
    """
    raw = raw or {}
    max_spend = _bounded_float(raw.get("maxSpendUsd"), 5.0, 0.0, 100.0)
    max_proxy = _bounded_float(raw.get("maxProxyCostUsd"), 0.5, 0.0, 20.0)
    if max_proxy > max_spend:
        max_proxy = max_spend
    prices = dict(DEFAULT_PRICES_USD)
    if prices_usd:
        prices.update(prices_usd)
    return {
        "max_spend_usd": max_spend,
        "max_proxy_usd": max_proxy,
        "allow_captcha": _flag(raw.get("allowCaptcha"), False),
        "proxy_groups": _proxy_groups(raw),
        "proxy_configuration": _proxy_configuration_dict(raw),
        "prices_usd": prices,
    }


def build_proxy_input(settings, *, escalate=False):
    """Input for Actor.create_proxy_configuration.

    Returns None until a block sets escalate. The first attempt stays direct
    even when the form leaves the proxy editor off. On escalate the group is
    the one from input, or datacenter when the input did not choose one.
    """
    settings = settings or {}
    if not escalate:
        return None
    groups = list(settings.get("proxy_groups") or []) or [DEFAULT_PROXY_GROUP]
    payload = {
        "useApifyProxy": True,
        "apifyProxyGroups": groups,
    }
    country = (settings.get("proxy_configuration") or {}).get("apifyProxyCountry")
    if isinstance(country, str) and country.strip():
        payload["apifyProxyCountry"] = country.strip()
    return payload


class SpendLedger:
    """Run spend in cents. can() is the check before a paid action."""

    def __init__(self, max_spend_usd, max_proxy_usd, prices_usd=None):
        prices = dict(DEFAULT_PRICES_USD)
        if prices_usd:
            prices.update(prices_usd)
        self.prices = {name: to_cents(amount) for name, amount in prices.items()}
        self.max_spend = max(0, to_cents(max_spend_usd))
        self.max_proxy = min(max(0, to_cents(max_proxy_usd)), self.max_spend)
        self.spent = 0
        self.proxy_spent = 0
        self.counts = {name: 0 for name in self.prices}

    def can(self, event):
        price = self.prices.get(event)
        if price is None:
            return False
        if self.spent + price > self.max_spend:
            return False
        if event == PROXY_EVENT and self.proxy_spent + price > self.max_proxy:
            return False
        return True

    def commit(self, event):
        price = self.prices[event]
        self.spent += price
        if event == PROXY_EVENT:
            self.proxy_spent += price
        self.counts[event] = self.counts.get(event, 0) + 1

    @property
    def spend_usd(self):
        return round(self.spent / 100, 2)

    @property
    def proxy_spend_usd(self):
        return round(self.proxy_spent / 100, 2)


class Decision:
    def __init__(self, action, stop=None, token=None):
        self.action = action
        self.stop = stop
        self.token = token


class AccessPolicy:
    """Spend ledger plus the block ladder for one run."""

    def __init__(self, settings, solver=None):
        self.settings = settings
        self.allow_captcha = bool(settings.get("allow_captcha"))
        self.solver = solver
        self.ledger = SpendLedger(
            settings["max_spend_usd"],
            settings["max_proxy_usd"],
            settings.get("prices_usd"),
        )

    def on_direct(self, result):
        if not is_block(result):
            return Decision("keep")
        if not self.ledger.can(PROXY_EVENT):
            log.critical("Blocked with no proxy budget left.")
            return Decision("stop", "budget")
        return Decision("proxy")

    def commit_proxy(self):
        if not self.ledger.can(PROXY_EVENT):
            return False
        self.ledger.commit(PROXY_EVENT)
        log.critical("Proxy retry after a block. Proxy events so far: %s.", self.ledger.counts[PROXY_EVENT])
        return True

    def on_proxy(self, result):
        if not is_block(result):
            return Decision("keep")
        if not is_captcha(result):
            return Decision("stop", "challenge")
        if not self.allow_captcha:
            log.critical("CAPTCHA. Solving is off for this run.")
            return Decision("stop", "captcha_disabled")
        if not self.ledger.can(CAPTCHA_EVENT):
            log.critical("CAPTCHA. Spend cap would not cover a solve.")
            return Decision("stop", "budget")
        if self.solver is None:
            return Decision("stop", "captcha_unavailable")
        return Decision("captcha")

    def solve(self, url, html):
        if self.solver is None:
            return Decision("stop", "captcha_unavailable")
        token = self.solver(url, html or "")
        if not token:
            log.critical("CAPTCHA on %s. No solver is configured, so nothing was billed.", url)
            return Decision("stop", "captcha_unavailable")
        if not self.ledger.can(CAPTCHA_EVENT):
            return Decision("stop", "budget")
        self.ledger.commit(CAPTCHA_EVENT)
        log.critical("CAPTCHA solve used for %s.", url)
        return Decision("retry", token=token)

    def on_captcha_retry(self, result):
        if is_block(result):
            return Decision("stop", "challenge")
        return Decision("keep")


def looks_json(result):
    ctype = ((result or {}).get("content_type") or "").lower()
    if "json" in ctype:
        return True
    text = ((result or {}).get("text") or "").lstrip()
    return text.startswith("{") or text.startswith("[")


def is_captcha(result):
    if looks_json(result):
        return False
    haystack = f"{(result or {}).get('text') or ''} {(result or {}).get('url') or ''}".lower()
    return any(marker in haystack for marker in CHALLENGE_MARKERS)


def is_block(result):
    """401, 403, 429, or a challenge page. A robots skip is not a block."""
    result = result or {}
    if result.get("error") in _NOT_BLOCKS:
        return False
    if result.get("stop"):
        return False
    status = int(result.get("status") or 0)
    if status in (401, 403, 429):
        return True
    return is_captcha(result)


def _mark(result, stop):
    body = dict(result or {})
    body["error"] = "blocked"
    body["stop"] = stop
    body.setdefault("status", 403)
    body.setdefault("text", "")
    body.setdefault("content_type", "text/html")
    return body


def after_proxy(policy, url, result, proxy):
    """Apply the CAPTCHA gate to a page that already came through the proxy."""
    decision = policy.on_proxy(result)
    if decision.action == "keep":
        return result, None
    if decision.action == "stop":
        return _mark(result, decision.stop), decision.stop
    solved = policy.solve(url, (result or {}).get("text") or "")
    if solved.action != "retry":
        return _mark(result, solved.stop or "captcha_unavailable"), solved.stop or "captcha_unavailable"
    retried = proxy(url, token=solved.token) or {}
    retried.setdefault("status", 0)
    retried.setdefault("text", "")
    retried.setdefault("content_type", "text/html")
    retried["url"] = retried.get("url") or url
    retried["via"] = "proxy"
    follow = policy.on_captcha_retry(retried)
    if follow.action == "stop":
        return _mark(retried, follow.stop), follow.stop
    return retried, None


def escalate(policy, url, direct_result, proxy):
    """Retry direct_result through proxy, then the CAPTCHA gate.

    proxy(url, token=None) performs the proxied request. None, or a result
    with error proxy_unavailable, spends nothing. The proxy event is committed
    only after that call returns a real attempt.
    """
    direct_result = dict(direct_result or {})
    decision = policy.on_direct(direct_result)
    if decision.action == "keep":
        return direct_result, None
    if decision.action == "stop":
        return _mark(direct_result, decision.stop), decision.stop
    if proxy is None:
        log.critical("Blocked and no proxy hook is configured.")
        return _mark(direct_result, "proxy_unavailable"), "proxy_unavailable"
    proxied = proxy(url, token=None) or {}
    if proxied.get("error") == "proxy_unavailable":
        log.critical("Blocked and Apify Proxy credentials are not set.")
        return _mark(direct_result, "proxy_unavailable"), "proxy_unavailable"
    if not policy.commit_proxy():
        return _mark(direct_result, "budget"), "budget"
    proxied.setdefault("status", 0)
    proxied.setdefault("text", "")
    proxied.setdefault("content_type", "text/html")
    proxied["url"] = proxied.get("url") or url
    proxied["via"] = "proxy"
    return after_proxy(policy, url, proxied, proxy)


def block_page(session, url=""):
    """Block result from a browser session that recorded the last challenge."""
    html = getattr(session, "last_block_html", "") or ""
    page_url = getattr(session, "last_block_url", "") or url or ""
    return {
        "status": 403,
        "text": html,
        "url": page_url,
        "error": None,
        "content_type": "text/html",
    }


class FetchEscalator:
    """Direct fetch session. On a block, reopen through a proxy URL and retry.

    session.fetch(url, wait_for=None) returns (status, html, error).
    reopen(proxy_url) returns the next session. proxy_url_fn() is called
    only after a block, and an empty string stops as proxy_unavailable.
    """

    def __init__(self, session, policy, proxy_url_fn, reopen):
        self.inner = session
        self.policy = policy
        self.proxy_url_fn = proxy_url_fn or (lambda: "")
        self.reopen = reopen
        self.stop = None
        self.phase = "direct"
        self._wait = None

    def close(self):
        closer = getattr(self.inner, "close", None)
        if closer:
            closer()

    def _page(self, status, html, error, url):
        return {
            "status": status or 0,
            "text": html or "",
            "error": error,
            "url": url,
            "content_type": "text/html",
        }

    def _proxy(self, url, token=None):
        del token
        if self.phase != "proxy":
            proxy_url = self.proxy_url_fn() or ""
            if not proxy_url:
                return {
                    "status": 0,
                    "text": "",
                    "error": "proxy_unavailable",
                    "content_type": "text/html",
                    "url": url,
                }
            self.close()
            self.inner = self.reopen(proxy_url)
            self.phase = "proxy"
        status, html, error = self.inner.fetch(url, wait_for=self._wait)
        return self._page(status, html, error, url)

    def _finish(self, final, fallback_status, fallback_html):
        stop = final.get("stop")
        if stop:
            self.stop = stop
            return final.get("status") or fallback_status or 403, final.get("text") or fallback_html or "", stop_message(stop)
        return final.get("status") or 200, final.get("text") or "", final.get("error")

    def fetch(self, url, wait_for=None):
        self._wait = wait_for
        if self.stop:
            return 403, "", stop_message(self.stop)
        if self.phase == "proxy":
            if not self.policy.ledger.can(PROXY_EVENT):
                self.stop = "budget"
                return 403, "", stop_message("budget")
            status, html, error = self.inner.fetch(url, wait_for=wait_for)
            result = self._page(status, html, error, url)
            if not self.policy.commit_proxy():
                self.stop = "budget"
                return status, html, stop_message("budget")
            if not is_block(result):
                return status, html, error
            final, _stop = after_proxy(self.policy, url, result, self._proxy)
            return self._finish(final, status, html)
        status, html, error = self.inner.fetch(url, wait_for=wait_for)
        result = self._page(status, html, error, url)
        if not is_block(result):
            return status, html, error
        final, _stop = escalate(self.policy, url, result, self._proxy)
        return self._finish(final, status, html)


def access_summary(settings, ledger):
    groups = list(settings.get("proxy_groups") or []) or [DEFAULT_PROXY_GROUP]
    return {
        "maxSpendUsd": settings["max_spend_usd"],
        "maxProxyCostUsd": settings["max_proxy_usd"],
        "allowCaptcha": bool(settings.get("allow_captcha")),
        "proxyGroups": groups,
        "spendUsd": ledger.spend_usd,
        "proxySpendUsd": ledger.proxy_spend_usd,
        "proxyCharges": ledger.counts.get(PROXY_EVENT, 0),
        "captchaCharges": ledger.counts.get(CAPTCHA_EVENT, 0),
    }


def proxy_url_from_env(groups=None, *, session=None):
    """Datacenter Apify Proxy URL from APIFY_PROXY_PASSWORD. Empty when unset."""
    password = os.environ.get("APIFY_PROXY_PASSWORD") or ""
    if not password:
        return ""
    chosen = [str(item).strip() for item in (groups or []) if str(item or "").strip()]
    group_name = "+".join(chosen) if chosen else DEFAULT_PROXY_GROUP
    host = os.environ.get("APIFY_PROXY_HOSTNAME") or "proxy.apify.com"
    port = os.environ.get("APIFY_PROXY_PORT") or "8000"
    session_id = session or uuid.uuid4().hex[:12]
    user = quote(f"groups-{group_name},session-{session_id}", safe="")
    secret = quote(password, safe="")
    return f"http://{user}:{secret}@{host}:{port}"


def playwright_proxy(proxy_url):
    """Playwright launch proxy dict, or None when the URL is empty."""
    if not proxy_url:
        return None
    parsed = urlparse(proxy_url)
    if not parsed.hostname:
        return None
    server = f"{parsed.scheme or 'http'}://{parsed.hostname}"
    if parsed.port:
        server = f"{server}:{parsed.port}"
    proxy = {"server": server}
    if parsed.username:
        proxy["username"] = unquote(parsed.username)
    if parsed.password:
        proxy["password"] = unquote(parsed.password)
    return proxy


async def create_proxy_configuration(settings=None, *, actor_input=None, escalate=False, actor=None):
    """Open Apify Proxy from actor input. None until escalate is true.

    ``actor`` is the Actor class or a stand-in with create_proxy_configuration.
    A platform error returns None so the run can push a blocked row.
    """
    settings = settings or read_access_settings(actor_input)
    proxy_input = build_proxy_input(settings, escalate=escalate)
    if not proxy_input:
        return None
    if actor is None:
        from apify import Actor
        actor = Actor
    try:
        return await actor.create_proxy_configuration(actor_proxy_input=proxy_input)
    except Exception as exc:
        log.critical("Could not open Apify Proxy: %s", exc)
        return None


async def new_proxy_url(configuration):
    if configuration is None:
        return ""
    new_url = getattr(configuration, "new_url", None)
    if new_url is None:
        return ""
    try:
        result = new_url()
        if asyncio.iscoroutine(result) or asyncio.isfuture(result):
            result = await result
    except Exception as exc:
        log.critical("Apify Proxy URL failed: %s", exc)
        return ""
    return result or ""


async def _proxy_url_async(settings):
    configuration = await create_proxy_configuration(settings=settings, escalate=True)
    url = await new_proxy_url(configuration)
    if url:
        return url
    return proxy_url_from_env(settings.get("proxy_groups"))


def blocking_proxy_url(settings, loop=None, context=None):
    """Proxy URL for a worker thread. Uses the Actor loop when one is running.

    ``context`` is the Actor task context captured before the scrape thread
    starts, so create_proxy_configuration still sees the run. Without a loop,
    fall back to APIFY_PROXY_PASSWORD. An empty string means the retry must
    stop as proxy_unavailable.
    """
    if loop is None:
        return proxy_url_from_env(settings.get("proxy_groups"))
    coro = _proxy_url_async(settings)
    if context is None:
        future = asyncio.run_coroutine_threadsafe(coro, loop)
    else:
        future = concurrent.futures.Future()

        def _start():
            try:
                task = loop.create_task(coro, context=context)
            except TypeError:
                task = loop.create_task(coro)

            def _finish(done):
                if future.done():
                    return
                if done.cancelled():
                    future.cancel()
                    return
                error = done.exception()
                if error is not None:
                    future.set_exception(error)
                else:
                    future.set_result(done.result())

            task.add_done_callback(_finish)

        loop.call_soon_threadsafe(_start)
    try:
        return future.result(timeout=60) or ""
    except Exception as exc:
        log.critical("Proxy configuration failed: %s", exc)
        return proxy_url_from_env(settings.get("proxy_groups"))


def cached_proxy_url(settings, loop=None):
    """Return a zero-arg function that resolves the proxy URL once per run."""
    context = contextvars.copy_context()
    cache = {"url": None}

    def get():
        if cache["url"] is None:
            cache["url"] = blocking_proxy_url(settings, loop, context) or ""
        return cache["url"]

    return get


async def charge_usage(ledger):
    """Charge proxy and CAPTCHA events the ledger already committed.

    Direct requests are not charged. Returns True when the platform cap
    stopped a later event. Rows are still saved by the caller.
    """
    if ledger is None:
        return False
    from apify import Actor

    capped = False
    for event in (PROXY_EVENT, CAPTCHA_EVENT):
        for _ in range(int(ledger.counts.get(event) or 0)):
            if capped:
                break
            result = await Actor.charge(event_name=event)
            if getattr(result, "event_charge_limit_reached", False):
                capped = True
                log.critical("%s charge limit reached. Later events are not billed.", event)
        if capped:
            break
    return capped


ACCESS_NAMES = (
    "PROXY_EVENT",
    "CAPTCHA_EVENT",
    "DEFAULT_PROXY_GROUP",
    "DEFAULT_PRICES_USD",
    "STOP_MESSAGES",
    "SpendLedger",
    "AccessPolicy",
    "read_access_settings",
    "build_proxy_input",
    "create_proxy_configuration",
    "new_proxy_url",
    "proxy_url_from_env",
    "blocking_proxy_url",
    "cached_proxy_url",
    "playwright_proxy",
    "is_block",
    "is_captcha",
    "escalate",
    "after_proxy",
    "stop_message",
    "access_summary",
    "charge_usage",
    "FetchEscalator",
    "block_page",
)
