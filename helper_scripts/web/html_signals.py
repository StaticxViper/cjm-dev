"""Shared HTML signals used by the website analyzers.

Each analyzer keeps its own score and return dict. These helpers only answer
the checks that were copied between them.
"""

from __future__ import annotations


def meta_content(soup, name=None, prop=None):
    if soup is None:
        return ""
    if name:
        tag = soup.find("meta", attrs={"name": lambda value: value and str(value).lower() == name.lower()})
    elif prop:
        tag = soup.find("meta", attrs={"property": lambda value: value and str(value).lower() == prop.lower()})
    else:
        return ""
    if not tag:
        return ""
    return (tag.get("content") or "").strip()


def has_title_tag(soup):
    return bool(soup is not None and soup.title and soup.title.string)


def title_text(soup):
    if not has_title_tag(soup):
        return ""
    return soup.title.string.strip()


def has_viewport(soup):
    if soup is None:
        return False
    return bool(
        soup.find("meta", attrs={"name": lambda value: value and str(value).lower() == "viewport"})
    )


def text_has_keywords(text, keywords):
    lowered = (text or "").lower()
    return any(keyword in lowered for keyword in keywords)


def is_https_url(url):
    return str(url or "").lower().startswith("https://")
