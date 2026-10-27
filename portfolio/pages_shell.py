"""Shared HTML shell for the portfolio, the apps hub, and the repo map."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONTENT_PATH = ROOT / "content.json"

SOURCE_NOTE = (
    "Source of truth for these pages is cjm-dev; other repos are linked only."
)

NAV = (
    ("index.html", "Home", "home"),
    ("projects.html", "Projects", "projects"),
    ("apps/index.html", "Apps", "apps"),
    ("repo-map/index.html", "Map", "map"),
    ("experience.html", "Experience", "experience"),
    ("about.html", "About", "about"),
    ("resume.html", "Resume", "resume"),
    ("contact.html", "Contact", "contact"),
)


def load_content() -> dict:
    return json.loads(CONTENT_PATH.read_text(encoding="utf-8"))


def esc(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def page_title(content: dict, *parts: str) -> str:
    return " — ".join((*parts, content["brand"]))


def assert_public_copy(text: str, label: str) -> None:
    """Reject holding-company and LLC wording on pages the site publishes."""
    lowered = text.lower()
    for phrase in ("moulton ventures", "holding company", "mv llc", "mv-llc", "llc"):
        if phrase in lowered:
            raise SystemExit(f"{label} still uses company branding ({phrase})")
    if "— Moulton" in text or ">Moulton<" in text or 'content="Moulton"' in text:
        raise SystemExit(f"{label} still uses Moulton as the company brand")


def rel(depth: int, path: str) -> str:
    return ("../" * depth) + path


def canonical_url(content: dict, path: str) -> str:
    site = content["siteUrl"]
    if not site.endswith("/"):
        site += "/"
    if path in ("", "index.html"):
        return site
    return site + path.lstrip("/")


def render_nav(active: str, depth: int) -> str:
    items = []
    for path, label, key in NAV:
        current = ' aria-current="page"' if key == active else ""
        items.append(f'<li><a href="{rel(depth, path)}"{current}>{esc(label)}</a></li>')
    return "<ul>" + "".join(items) + "</ul>"


def render_site_page(
    content: dict,
    title: str,
    description: str,
    canonical_path: str,
    body: str,
    active: str,
    depth: int = 0,
    mermaid: bool = False,
) -> str:
    canonical = canonical_url(content, canonical_path)
    image = canonical_url(content, "og.png")
    mermaid_script = ""
    if mermaid:
        mermaid_script = """
  <script type="module">
    import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";
    mermaid.initialize({ startOnLoad: true, securityLevel: "strict", theme: "dark" });
  </script>"""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <meta name="description" content="{esc(description)}">
  <meta name="author" content="{esc(content["name"])}">
  <meta name="theme-color" content="#070b0a">
  <link rel="canonical" href="{esc(canonical)}">
  <meta property="og:type" content="website">
  <meta property="og:title" content="{esc(title)}">
  <meta property="og:description" content="{esc(description)}">
  <meta property="og:url" content="{esc(canonical)}">
  <meta property="og:image" content="{esc(image)}">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:image:alt" content="{esc(content["brand"])}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{esc(title)}">
  <meta name="twitter:description" content="{esc(description)}">
  <meta name="twitter:image" content="{esc(image)}">
  <link rel="icon" href="{rel(depth, "favicon.svg")}" type="image/svg+xml">
  <link rel="stylesheet" href="{rel(depth, "site.css")}">{mermaid_script}
</head>
<body>
  <a class="skip" href="#content">Skip to content</a>
  <header class="site-header">
    <div class="wrap header-inner">
      <a class="brand" href="{rel(depth, "index.html")}">{esc(content["brand"])}</a>
      <button class="nav-toggle" type="button" aria-expanded="false" aria-controls="site-nav">Menu</button>
      <nav id="site-nav" class="site-nav" aria-label="Primary">
        {render_nav(active, depth)}
      </nav>
    </div>
  </header>
  <main id="content">
    <div class="wrap">
      {body}
    </div>
  </main>
  <footer class="site-footer">
    <div class="wrap footer-inner">
      <p>{esc(content["brand"])} · Portfolio</p>
      <p>{esc(content["location"])}</p>
    </div>
  </footer>
  <script>
    const toggle = document.querySelector(".nav-toggle");
    const nav = document.querySelector("#site-nav");
    toggle.addEventListener("click", () => {{
      const open = nav.classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.textContent = open ? "Close" : "Menu";
    }});
    nav.addEventListener("click", (event) => {{
      if (event.target.closest("a")) {{
        nav.classList.remove("is-open");
        toggle.setAttribute("aria-expanded", "false");
        toggle.textContent = "Menu";
      }}
    }});
  </script>
</body>
</html>
"""


def markdown_to_html(text: str, *, depth: int = 0) -> str:
    html = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("```"):
            lang = line[3:].strip()
            block = []
            index += 1
            while index < len(lines) and not lines[index].startswith("```"):
                block.append(lines[index])
                index += 1
            code = "\n".join(block)
            if lang == "mermaid":
                html.append(f'<div class="diagram"><pre class="mermaid">{esc(code)}</pre></div>')
            else:
                html.append(f'<pre class="code">{esc(code)}</pre>')
        elif line.startswith("### "):
            html.append(f"<h3>{inline(line[4:], depth)}</h3>")
        elif line.startswith("## "):
            html.append(f"<h2>{inline(line[3:], depth)}</h2>")
        elif line.startswith("# "):
            html.append(f"<h1>{inline(line[2:], depth)}</h1>")
        elif line.startswith("- "):
            items = []
            while index < len(lines) and lines[index].startswith("- "):
                items.append(f"<li>{inline(lines[index][2:], depth)}</li>")
                index += 1
            html.append("<ul>" + "".join(items) + "</ul>")
            continue
        elif _ordered_item(line) is not None:
            items = []
            while index < len(lines) and _ordered_item(lines[index]) is not None:
                items.append(f"<li>{inline(_ordered_item(lines[index]), depth)}</li>")
                index += 1
            html.append("<ol>" + "".join(items) + "</ol>")
            continue
        elif line.strip():
            html.append(f"<p>{inline(line, depth)}</p>")
        index += 1
    return "\n".join(html)


def inline(value: str, depth: int) -> str:
    escaped = esc(value).replace("**", "\x00")
    bolded = []
    open_bold = False
    for char in escaped:
        if char == "\x00":
            bolded.append("</strong>" if open_bold else "<strong>")
            open_bold = not open_bold
            continue
        bolded.append(char)
    text = "".join(bolded)
    out = []
    index = 0
    while index < len(text):
        if text.startswith("`", index):
            end = text.find("`", index + 1)
            if end != -1:
                out.append("<code>" + text[index + 1:end] + "</code>")
                index = end + 1
                continue
        if text.startswith("[", index):
            mid = text.find("](", index)
            end = text.find(")", mid + 2) if mid != -1 else -1
            if mid != -1 and end != -1:
                label = text[index + 1:mid]
                href = resolve_href(text[mid + 2:end], depth)
                attrs = ""
                if href.startswith("http://") or href.startswith("https://"):
                    attrs = ' target="_blank" rel="noopener noreferrer"'
                out.append(f'<a href="{href}"{attrs}>{label}</a>')
                index = end + 1
                continue
        out.append(text[index])
        index += 1
    return "".join(out)


def _ordered_item(line: str) -> str | None:
    number, separator, rest = line.partition(". ")
    if separator and number.isdigit() and rest:
        return rest
    return None


def resolve_href(href: str, depth: int) -> str:
    if href.startswith("site:"):
        return rel(depth, href[5:])
    if href.endswith(".md") and "/" not in href and "\\" not in href:
        return href[:-3] + ".html"
    return href
