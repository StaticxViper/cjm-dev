"""Render documentation/apps into the Pages site under dist/apps/."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from pages_shell import SOURCE_NOTE, esc, load_content, markdown_to_html, rel, render_site_page

PORTFOLIO = Path(__file__).resolve().parent
REPO = PORTFOLIO.parent
APPS = REPO / "documentation" / "apps"
CATALOG_PATH = APPS / "catalog.json"
CJM_REPO = "https://github.com/StaticxViper/cjm-dev"
CODE_LABELS = {
    "this-repo": "In this repo",
    "external": "Other repo",
    "unrecorded": "Repo not recorded",
}


def load_catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def portfolio_slugs() -> dict[str, str]:
    catalog = load_catalog()
    return {
        project["portfolioName"]: project["slug"]
        for project in catalog["projects"]
        if project.get("portfolioName")
    }


def validate_catalog(catalog: dict, content: dict | None = None) -> None:
    if catalog.get("sourceNote") != SOURCE_NOTE:
        raise SystemExit("catalog.json sourceNote must be the cjm-dev source-of-truth sentence")
    projects = catalog.get("projects")
    if not isinstance(projects, list) or not projects:
        raise SystemExit("catalog.json needs a projects array")
    content = content if content is not None else load_content()
    names = {project["name"] for project in content["projects"]}
    slugs: set[str] = set()
    for project in projects:
        name = project.get("name") or "(unnamed)"
        slug = project.get("slug") or ""
        if not _slug_ok(slug):
            raise SystemExit(f"{name}: slug must be lowercase words separated by hyphens")
        if slug in slugs:
            raise SystemExit(f"Duplicate app slug: {slug}")
        slugs.add(slug)
        if not project.get("name") or not project.get("summary"):
            raise SystemExit(f"{slug}: name and summary are required")
        code = project.get("code")
        if code not in CODE_LABELS:
            raise SystemExit(f"{name}: code must be this-repo, external, or unrecorded")
        _validate_github(name, code, project.get("github"))
        _validate_live(name, project.get("live"))
        _validate_diagrams(name, project.get("diagrams"))
        folder = APPS / slug
        for filename in ("HOW_IT_WORKS.md", "CHANGELOG.md"):
            path = folder / filename
            if not path.is_file() or not path.read_text(encoding="utf-8").strip():
                raise SystemExit(f"{name}: missing {path.relative_to(REPO).as_posix()}")
        portfolio_name = project.get("portfolioName")
        if portfolio_name and portfolio_name not in names:
            raise SystemExit(f"{name}: portfolioName is not a project in content.json")


def _slug_ok(slug: str) -> bool:
    if not slug or slug[0] == "-" or slug[-1] == "-":
        return False
    parts = slug.split("-")
    return all(part.isascii() and part.isalnum() and part == part.lower() for part in parts)


def _validate_github(name: str, code: str, github: object) -> None:
    if code == "unrecorded":
        if github:
            raise SystemExit(f"{name}: leave github empty until the repo URL is known")
        return
    if not isinstance(github, dict):
        raise SystemExit(f"{name}: github owner, name, and url are required")
    owner = str(github.get("owner") or "")
    repo = str(github.get("name") or "")
    url = str(github.get("url") or "")
    if not owner or not repo or "/" in owner or "/" in repo:
        raise SystemExit(f"{name}: github owner and name are the reference, not a path")
    if not url.startswith("https://github.com/"):
        raise SystemExit(f"{name}: github url must be an https://github.com link")
    if code == "this-repo" and not url.startswith(CJM_REPO):
        raise SystemExit(f"{name}: this-repo links have to stay inside {CJM_REPO}")
    if code == "external" and url.startswith(CJM_REPO):
        raise SystemExit(f"{name}: code in cjm-dev uses code this-repo")


def _validate_live(name: str, live: object) -> None:
    if live is None:
        return
    if not isinstance(live, dict) or not str(live.get("url") or "").startswith("https://"):
        raise SystemExit(f"{name}: live url must start with https://")
    if not live.get("label"):
        raise SystemExit(f"{name}: live link needs a label")


def _validate_diagrams(name: str, diagrams: object) -> None:
    if not isinstance(diagrams, list):
        raise SystemExit(f"{name}: diagrams must be a list, or [] when this repo has no diagram")
    for diagram in diagrams:
        href = str(diagram.get("href") or "")
        label = str(diagram.get("label") or "")
        if not label:
            raise SystemExit(f"{name}: a diagram link needs a label")
        if not href.startswith("repo-map/") or not href.endswith(".html"):
            raise SystemExit(f"{name}: diagram href must be a repo-map HTML path")
        if ".." in href or "://" in href:
            raise SystemExit(f"{name}: diagram href stays on this site")
        if _diagram_source(href) is None:
            raise SystemExit(f"{name}: no diagram source for {href}")


def _diagram_source(href: str) -> Path | None:
    if href == "repo-map/index.html":
        overview = REPO / "documentation" / "repo-map" / "overview.md"
        return overview if overview.is_file() else None
    filename = href.removeprefix("repo-map/")
    if not filename.endswith(".html"):
        return None
    markdown = filename[:-5] + ".md"
    hand = REPO / "documentation" / "repo-map" / markdown
    generated = REPO / "documentation" / "repo-map" / "generated" / markdown
    if hand.is_file():
        return hand
    if generated.is_file():
        return generated
    return None


def render_apps(dest: Path | None = None) -> int:
    content = load_content()
    catalog = load_catalog()
    validate_catalog(catalog, content)
    dest = dest or (PORTFOLIO / "dist" / "apps")
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    projects = catalog["projects"]
    (dest / "index.html").write_text(_index_page(content, projects), encoding="utf-8")
    count = 1
    for project in projects:
        folder = dest / project["slug"]
        folder.mkdir()
        (folder / "index.html").write_text(_overview_page(content, project), encoding="utf-8")
        (folder / "how-it-works.html").write_text(_markdown_page(content, project, "how"), encoding="utf-8")
        (folder / "changelog.html").write_text(_markdown_page(content, project, "changelog"), encoding="utf-8")
        count += 3
    return count


def _index_page(content: dict, projects: list[dict]) -> str:
    cards = "\n".join(_index_card(project) for project in projects)
    body = f"""
      <header class="page-intro">
        <p class="eyebrow">Map · How it works · Changelog</p>
        <h1>Apps</h1>
        <p class="lede">Click a project to see what it does now, what changed, and the diagrams that match.</p>
        <p class="truth">{esc(SOURCE_NOTE)}</p>
      </header>
      <div class="layer-grid">
        <a class="layer-card" href="{rel(1, "repo-map/index.html")}">
          <p class="labels">Map</p>
          <h2>Diagrams</h2>
          <p>Import and call diagrams for the code in this repo.</p>
        </a>
        <a class="layer-card" href="#projects">
          <p class="labels">How it works</p>
          <h2>Right now</h2>
          <p>One short page per app: the product, the main flows, and where the code lives.</p>
        </a>
        <a class="layer-card" href="#projects">
          <p class="labels">Changelog</p>
          <h2>What changed</h2>
          <p>Dated notes, so a publish does not mean reading the diff.</p>
        </a>
      </div>
      <section class="section" aria-labelledby="flow-heading">
        <h2 id="flow-heading">Click through</h2>
        <div class="diagram"><pre class="mermaid">flowchart LR
  hub["Apps index"] --> project["Project"]
  project --> how["How it works"]
  project --> changes["Changelog"]
  project --> diagrams["Repo map"]</pre></div>
      </section>
      <section class="section" id="projects" aria-labelledby="projects-heading">
        <h2 id="projects-heading">Projects</h2>
        <div class="work-list">
          {cards}
        </div>
      </section>
    """
    return render_site_page(
        content,
        title="Apps — Moulton",
        description="How CJ's apps work, what changed, and where the code lives.",
        canonical_path="apps/index.html",
        body=body,
        active="apps",
        depth=1,
        mermaid=True,
    )


def _index_card(project: dict) -> str:
    slug = project["slug"]
    diagram_link = ""
    if project["diagrams"]:
        diagram = project["diagrams"][0]
        diagram_link = (
            f'<p class="work-link"><a href="{rel(1, diagram["href"])}">{esc(diagram["label"])}</a></p>'
        )
    return f"""
            <article class="work">
              <span class="mark" aria-hidden="true">{esc(project["name"][:1].upper())}</span>
              <div class="work-copy">
                <div class="work-heading">
                  <h3><a href="{esc(slug)}/index.html">{esc(project["name"])}</a></h3>
                  <p class="labels"><span>{esc(CODE_LABELS[project["code"]])}</span></p>
                </div>
                <p>{esc(project["summary"])}</p>
                <div class="link-row">
                  <p class="work-link"><a href="{esc(slug)}/index.html">Open</a></p>
                  <p class="work-link"><a href="{esc(slug)}/how-it-works.html">How it works</a></p>
                  <p class="work-link"><a href="{esc(slug)}/changelog.html">Changelog</a></p>
                  {_github_link(project)}
                  {_live_link(project)}
                  {diagram_link}
                </div>
              </div>
            </article>
    """


def _overview_page(content: dict, project: dict) -> str:
    slug = project["slug"]
    body = f"""
      <header class="page-intro">
        <p class="eyebrow">Apps</p>
        <h1>{esc(project["name"])}</h1>
        <p class="lede">{esc(project["summary"])}</p>
        {_layer_nav(project, "overview")}
        <p class="truth">{esc(SOURCE_NOTE)}</p>
      </header>
      <div class="link-row">
        <p class="work-link"><a class="button button-green" href="how-it-works.html">How it works</a></p>
        <p class="work-link"><a class="button button-line" href="changelog.html">Changelog</a></p>
        {_github_link(project)}
        {_live_link(project)}
      </div>
    """
    return render_site_page(
        content,
        title=f"{project['name']} — Moulton",
        description=project["summary"],
        canonical_path=f"apps/{slug}/index.html",
        body=body,
        active="apps",
        depth=2,
    )


def _markdown_page(content: dict, project: dict, kind: str) -> str:
    spec = {
        "how": ("HOW_IT_WORKS.md", "how-it-works.html", "How it works"),
        "changelog": ("CHANGELOG.md", "changelog.html", "Changelog"),
    }
    filename, html_name, heading = spec[kind]
    text = (APPS / project["slug"] / filename).read_text(encoding="utf-8")
    prose = markdown_to_html(_strip_title(text), depth=2)
    body = f"""
      <header class="page-intro">
        <p class="eyebrow">{esc(project["name"])}</p>
        <h1>{heading}</h1>
        {_layer_nav(project, kind)}
        <p class="truth">{esc(SOURCE_NOTE)}</p>
      </header>
      <div class="prose">
        {prose}
      </div>
    """
    return render_site_page(
        content,
        title=f"{project['name']} — {heading} — Moulton",
        description=project["summary"],
        canonical_path=f"apps/{project['slug']}/{html_name}",
        body=body,
        active="apps",
        depth=2,
        mermaid="```mermaid" in text,
    )


def _strip_title(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
        if lines and not lines[0].strip():
            lines = lines[1:]
    return "\n".join(lines)


def _layer_nav(project: dict, current: str) -> str:
    items = (
        ("index.html", "Overview", "overview"),
        ("how-it-works.html", "How it works", "how"),
        ("changelog.html", "Changelog", "changelog"),
    )
    links = []
    for href, label, key in items:
        attr = ' aria-current="page"' if key == current else ""
        links.append(f'<a href="{href}"{attr}>{esc(label)}</a>')
    for diagram in project["diagrams"]:
        links.append(
            f'<a href="{rel(2, diagram["href"])}">{esc(diagram["label"])}</a>'
        )
    return f'<nav class="layer-nav" aria-label="{esc(project["name"])}">{"".join(links)}</nav>'


def _github_link(project: dict) -> str:
    github = project.get("github")
    if not github:
        return '<p class="work-link pending">GitHub repo not recorded yet</p>'
    ref = f'{github["owner"]}/{github["name"]}'
    label = str(github.get("label") or "")
    text = ref if not label or label == ref else f"{ref} — {label}"
    return (
        '<p class="work-link"><a href="'
        f'{esc(github["url"])}" target="_blank" rel="noopener noreferrer">'
        f'{esc(text)}<span class="sr-only"> (opens in a new tab)</span></a></p>'
    )


def _live_link(project: dict) -> str:
    live = project.get("live")
    if not live:
        return ""
    return (
        f'<p class="work-link"><a href="{esc(live["url"])}" target="_blank" rel="noopener noreferrer">'
        f'{esc(live["label"])}<span class="sr-only"> (opens in a new tab)</span></a></p>'
    )


if __name__ == "__main__":
    written = render_apps()
    print(f"Rendered {written} app pages")
