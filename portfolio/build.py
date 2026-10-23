"""Generate the static Moulton site from portfolio/content.json."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from og_card import write_og_png
from resume_pdf import build_resume

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
PUBLIC = ROOT / "public"
CONTENT_PATH = ROOT / "content.json"

KINDS = {"website": "Website", "app": "App", "script": "Script"}
STATUSES = ("current", "completed", "planned")
STATUS_LABELS = {"current": "Current", "completed": "Completed", "planned": "Planned"}
PAGES = (
    ("index.html", "home"),
    ("projects.html", "projects"),
    ("experience.html", "experience"),
    ("about.html", "about"),
    ("resume.html", "resume"),
    ("contact.html", "contact"),
)
NAV = (
    ("index.html", "Home"),
    ("projects.html", "Projects"),
    ("experience.html", "Experience"),
    ("about.html", "About"),
    ("resume.html", "Resume"),
    ("contact.html", "Contact"),
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


def validate(content: dict) -> None:
    required = ("brand", "holdingCompany", "positioning", "pages", "about", "projects", "contact")
    missing = [key for key in required if key not in content]
    if missing:
        raise SystemExit(f"content.json is missing: {', '.join(missing)}")
    for filename, key in PAGES:
        page = content["pages"].get(key)
        if not page or not page.get("title") or not page.get("description"):
            raise SystemExit(f"content.json pages.{key} needs a title and description ({filename})")
    for index, project in enumerate(content["projects"], start=1):
        name = project.get("name") or f"#{index}"
        if project.get("kind") not in KINDS:
            raise SystemExit(f"{name}: kind must be website, app, or script")
        if project.get("status") not in STATUSES:
            raise SystemExit(f"{name}: status must be current, completed, or planned")
        if not isinstance(project.get("show"), bool) or not isinstance(project.get("featured"), bool):
            raise SystemExit(f"{name}: show and featured must be true or false")
        if not project.get("name") or not project.get("description"):
            raise SystemExit(f"Project {index} needs a name and description")


def shown_projects(content: dict) -> list[dict]:
    return [project for project in content["projects"] if project["show"]]


def render_mark(project: dict) -> str:
    logo = (project.get("logo") or "").strip()
    if logo:
        return f'<img class="mark" src="{esc(logo)}" alt="">'
    letter = esc(project["name"][:1].upper())
    return f'<span class="mark" aria-hidden="true">{letter}</span>'


def render_link(project: dict) -> str:
    url = (project.get("url") or "").strip()
    if not url:
        return '<p class="pending">Link coming soon</p>'
    label = (project.get("urlLabel") or "").strip() or "Open"
    new_tab = url.startswith("http")
    attributes = ' target="_blank" rel="noopener noreferrer"' if new_tab else ""
    note = '<span class="sr-only"> (opens in a new tab)</span>' if new_tab else ""
    return f'<p class="work-link"><a href="{esc(url)}"{attributes}>{esc(label)}{note}</a></p>'


def render_work(project: dict) -> str:
    tech = (project.get("tech") or "").strip()
    tech_html = f'<p class="tech">{esc(tech)}</p>' if tech else ""
    return f"""
            <article class="work">
              {render_mark(project)}
              <div class="work-copy">
                <div class="work-heading">
                  <h3>{esc(project["name"])}</h3>
                  <p class="labels"><span>{KINDS[project["kind"]]}</span><span>{STATUS_LABELS[project["status"]]}</span></p>
                </div>
                {tech_html}
                <p>{esc(project["description"])}</p>
                {render_link(project)}
              </div>
            </article>
    """


def render_experience(jobs: list[dict]) -> str:
    blocks = []
    for job in jobs:
        dates = "".join(f"<p>{esc(role['dates'])}</p>" for role in job["roles"])
        primary = job["roles"][0]
        prior = ""
        if len(job["roles"]) > 1:
            earlier = job["roles"][1]
            prior = (
                f'<p class="prior-role">Previously {esc(earlier["title"])}, '
                f'{esc(earlier["dates"])}</p>'
            )
        highlights = "".join(f"<li>{esc(item)}</li>" for item in job["highlights"])
        summary = f'<p class="summary">{esc(job["summary"])}</p>' if job.get("summary") else ""
        blocks.append(
            f"""
            <article class="role">
              <div class="dates">{dates}</div>
              <div>
                <h3>{esc(primary["title"])}</h3>
                <p class="org">{esc(job["company"])} · {esc(job["location"])}</p>
                {prior}
                {summary}
                <ul>{highlights}</ul>
              </div>
            </article>
            """
        )
    return "\n".join(blocks)


def render_skills(groups: list[dict]) -> str:
    cards = []
    for group in groups:
        items = "".join(f"<li>{esc(item)}</li>" for item in group["items"])
        cards.append(
            f"""
            <section class="skill-group">
              <h3>{esc(group["group"])}</h3>
              <ul>{items}</ul>
            </section>
            """
        )
    return "\n".join(cards)


def render_education(schools: list[dict]) -> str:
    blocks = []
    for school in schools:
        location = f" · {esc(school['location'])}" if school.get("location") else ""
        details = f'<p class="summary">{esc(school["details"])}</p>' if school.get("details") else ""
        blocks.append(
            f"""
            <article class="school">
              <div class="dates"><p>{esc(school["dates"])}</p></div>
              <div>
                <h3>{esc(school["credential"])}</h3>
                <p class="org">{esc(school["school"])}{location}</p>
                {details}
              </div>
            </article>
            """
        )
    return "\n".join(blocks)


def render_plain_list(items: list[str]) -> str:
    return '<ul class="plain-list">' + "".join(f"<li>{esc(item)}</li>" for item in items) + "</ul>"


def render_nav(active: str) -> str:
    items = []
    for filename, label in NAV:
        current = ' aria-current="page"' if filename == active else ""
        items.append(f'<li><a href="{filename}"{current}>{label}</a></li>')
    return "<ul>" + "".join(items) + "</ul>"


def render_contact_items(contact: dict, *, include_phone: bool) -> str:
    rows = [
        ("Email", f'<a href="mailto:{esc(contact["email"])}">{esc(contact["email"])}</a>'),
    ]
    if include_phone:
        rows.append(("Phone", f'<a href="{esc(contact["phoneHref"])}">{esc(contact["phone"])}</a>'))
    rows.append((
        "LinkedIn",
        f'<a href="{esc(contact["linkedin"])}" target="_blank" rel="noopener noreferrer">{esc(contact["linkedinLabel"])}<span class="sr-only"> (opens in a new tab)</span></a>',
    ))
    rows.append((
        "GitHub",
        f'<a href="{esc(contact["github"])}" target="_blank" rel="noopener noreferrer">{esc(contact["githubLabel"])}<span class="sr-only"> (opens in a new tab)</span></a>',
    ))
    return "".join(f"<li><span>{label}</span>{value}</li>" for label, value in rows)


def layout(content: dict, filename: str, body: str) -> str:
    page_key = dict(PAGES)[filename]
    page = content["pages"][page_key]
    site = content["siteUrl"]
    if not site.endswith("/"):
        site += "/"
    canonical = site if filename == "index.html" else site + filename
    image = site + "og.png"
    title = esc(page["title"])
    description = esc(page["description"])
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <meta name="description" content="{description}">
  <meta name="author" content="{esc(content["name"])}">
  <meta name="theme-color" content="#070b0a">
  <link rel="canonical" href="{esc(canonical)}">
  <meta property="og:type" content="website">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{description}">
  <meta property="og:url" content="{esc(canonical)}">
  <meta property="og:image" content="{esc(image)}">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:image:alt" content="{esc(content["brand"])}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{title}">
  <meta name="twitter:description" content="{description}">
  <meta name="twitter:image" content="{esc(image)}">
  <link rel="icon" href="favicon.svg" type="image/svg+xml">
  <link rel="stylesheet" href="site.css">
</head>
<body>
  <a class="skip" href="#content">Skip to content</a>
  <header class="site-header">
    <div class="wrap header-inner">
      <a class="brand" href="index.html">{esc(content["brand"])}</a>
      <button class="nav-toggle" type="button" aria-expanded="false" aria-controls="site-nav">Menu</button>
      <nav id="site-nav" class="site-nav" aria-label="Primary">
        {render_nav(filename)}
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
      <p>{esc(content["brand"])} · {esc(content["holdingCompany"])}</p>
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


def page_home(content: dict, projects: list[dict]) -> str:
    featured = [project for project in projects if project["featured"]]
    work = "\n".join(render_work(project) for project in featured)
    featured_block = ""
    if featured:
        featured_block = f"""
      <section class="section" aria-labelledby="selected-heading">
        <h2 id="selected-heading">Selected work</h2>
        <div class="work-list">
          {work}
        </div>
      </section>
        """
    return f"""
      <section class="hero" aria-labelledby="home-heading">
        <p class="eyebrow">{esc(content["holdingCompany"])}</p>
        <h1 id="home-heading">{esc(content["brand"])}</h1>
        <p class="lede">{esc(content["positioning"])}</p>
        <div class="actions">
          <a class="button button-green" href="projects.html">View projects</a>
          <a class="button button-line" href="contact.html">Contact</a>
        </div>
      </section>
      {featured_block}
      <section class="section" aria-labelledby="connect-heading">
        <h2 id="connect-heading">Connect</h2>
        <ul class="contact-list">
          {render_contact_items(content["contact"], include_phone=False)}
        </ul>
      </section>
    """


def page_projects(content: dict, projects: list[dict]) -> str:
    groups = []
    for status in STATUSES:
        items = [project for project in projects if project["status"] == status]
        body = "\n".join(render_work(project) for project in items) if items else '<p class="empty">Nothing in this group yet.</p>'
        groups.append(
            f"""
      <section class="section" id="{status}" aria-labelledby="{status}-heading">
        <h2 id="{status}-heading">{STATUS_LABELS[status]}</h2>
        <div class="work-list">
          {body}
        </div>
      </section>
            """
        )
    intro = content["pages"]["projects"].get("intro", "")
    intro_html = f'<p class="lede">{esc(intro)}</p>' if intro else ""
    return f"""
      <header class="page-intro">
        <h1>Projects</h1>
        {intro_html}
      </header>
      {''.join(groups)}
    """


def page_experience(content: dict) -> str:
    credentials = "".join(f"<li>{esc(item)}</li>" for item in content["credentials"])
    intro = content["pages"]["experience"].get("intro", "")
    intro_html = f'<p class="lede">{esc(intro)}</p>' if intro else ""
    return f"""
      <header class="page-intro">
        <h1>Experience</h1>
        {intro_html}
        <p class="person-line">{esc(content["name"])} · {esc(content["headline"])}</p>
        <ul class="credentials">{credentials}</ul>
      </header>
      <section class="section" aria-labelledby="roles-heading">
        <h2 id="roles-heading">Roles</h2>
        {render_experience(content["experience"])}
      </section>
      <section class="section" aria-labelledby="skills-heading">
        <h2 id="skills-heading">Skills</h2>
        <div class="skill-grid">
          {render_skills(content["skills"])}
        </div>
      </section>
      <section class="section" aria-labelledby="education-heading">
        <h2 id="education-heading">Education</h2>
        {render_education(content["education"])}
      </section>
      <section class="section" aria-labelledby="certifications-heading">
        <h2 id="certifications-heading">Certifications</h2>
        {render_plain_list(content["certifications"])}
      </section>
      <section class="section" aria-labelledby="honors-heading">
        <h2 id="honors-heading">Honors</h2>
        {render_plain_list(content["honors"])}
      </section>
    """


def page_about(content: dict) -> str:
    about = content["about"]
    person = "".join(f"<p>{esc(paragraph)}</p>" for paragraph in about["person"])
    company = "".join(f"<p>{esc(paragraph)}</p>" for paragraph in about["company"])
    return f"""
      <header class="page-intro">
        <h1>About</h1>
      </header>
      <div class="split">
        <section aria-labelledby="person-heading">
          <h2 id="person-heading">{esc(about["personTitle"])}</h2>
          {person}
        </section>
        <section aria-labelledby="company-heading">
          <h2 id="company-heading">{esc(about["companyTitle"])}</h2>
          {company}
        </section>
      </div>
    """


def page_resume(content: dict) -> str:
    contact = content["contact"]
    resume = esc(content["resumeFile"])
    intro = content["pages"]["resume"].get("intro", "")
    intro_html = f'<p class="lede">{esc(intro)}</p>' if intro else ""
    return f"""
      <header class="page-intro">
        <h1>Resume</h1>
        {intro_html}
        <div class="actions">
          <a class="button button-green" href="{resume}" download>Download resume (PDF)</a>
          <a class="button button-line" href="{esc(contact["linkedin"])}" target="_blank" rel="noopener noreferrer">LinkedIn profile<span class="sr-only"> (opens in a new tab)</span></a>
        </div>
      </header>
    """


def page_contact(content: dict) -> str:
    return f"""
      <header class="page-intro">
        <h1>Contact</h1>
        <p class="lede">{esc(content["preferredName"])}</p>
      </header>
      <ul class="contact-list">
        {render_contact_items(content["contact"], include_phone=True)}
      </ul>
    """


def copy_logos(projects: list[dict]) -> None:
    seen: set[str] = set()
    for project in projects:
        logo = (project.get("logo") or "").strip()
        if not logo or logo.startswith("http") or logo in seen:
            continue
        seen.add(logo)
        source = PUBLIC / logo if (PUBLIC / logo).is_file() else ROOT / logo
        if not source.is_file():
            raise SystemExit(f"Missing logo file for {project['name']}: {logo}")
        dest = DIST / logo
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)


def check(content: dict, pages: dict[str, str], resume_path: Path, og_path: Path) -> None:
    shown = shown_projects(content)
    hidden = [project for project in content["projects"] if not project["show"]]
    featured = [project for project in shown if project["featured"]]
    combined = "\n".join(pages.values())
    resume_bytes = resume_path.read_bytes()
    for project in hidden:
        if project["name"] in combined:
            raise SystemExit(f"Hidden project was published: {project['name']}")
        if project["name"].encode("utf-8") in resume_bytes:
            raise SystemExit(f"Hidden project was written into the resume: {project['name']}")
    projects_html = pages["projects.html"]
    home = pages["index.html"]
    for project in shown:
        if project["name"] not in projects_html:
            raise SystemExit(f"Shown project missing from Projects: {project['name']}")
        if project["featured"] and project["name"] not in home:
            raise SystemExit(f"Featured project missing from Home: {project['name']}")
        if not project["featured"] and project["name"] in home:
            raise SystemExit(f"Project is on Home without featured set: {project['name']}")
    for status in STATUSES:
        if f'id="{status}"' not in projects_html:
            raise SystemExit(f"Projects page is missing the {status} group")
    if "<h1>Moulton</h1>" not in home and "<h1 id=\"home-heading\">Moulton</h1>" not in home:
        raise SystemExit("Home page is missing the Moulton heading")
    if "ASRC Federal" in home:
        raise SystemExit("Home page still contains the resume experience")
    if "Download resume (PDF)" not in pages["resume.html"]:
        raise SystemExit("Resume download link is missing")
    linkedin = content["contact"]["linkedin"]
    github = content["contact"]["github"]
    if linkedin not in pages["resume.html"] or linkedin not in pages["contact.html"]:
        raise SystemExit("LinkedIn link is missing")
    if github not in pages["contact.html"] or github not in home:
        raise SystemExit("GitHub link is missing")
    if any(not (project.get("url") or "").strip() for project in shown) and "Link coming soon" not in projects_html:
        raise SystemExit("A project without a link is missing the placeholder")
    for filename, html in pages.items():
        if 'id="content"' not in html or "og:image" not in html or "Skip to content" not in html:
            raise SystemExit(f"{filename} is missing the shared page shell")
        if html.count("<h1") != 1:
            raise SystemExit(f"{filename} should have one h1")
    if not resume_path.is_file() or resume_path.stat().st_size < 1000:
        raise SystemExit("Resume PDF was not written")
    if not og_path.is_file() or og_path.stat().st_size < 1000:
        raise SystemExit("Social preview image was not written")


def build() -> None:
    content = load_content()
    validate(content)
    projects = shown_projects(content)
    pages = {
        "index.html": layout(content, "index.html", page_home(content, projects)),
        "projects.html": layout(content, "projects.html", page_projects(content, projects)),
        "experience.html": layout(content, "experience.html", page_experience(content)),
        "about.html": layout(content, "about.html", page_about(content)),
        "resume.html": layout(content, "resume.html", page_resume(content)),
        "contact.html": layout(content, "contact.html", page_contact(content)),
    }

    resume_name = content["resumeFile"]
    PUBLIC.mkdir(exist_ok=True)
    public_resume = PUBLIC / resume_name
    resume_content = dict(content)
    resume_content["projects"] = projects
    if content.get("generateResume", True):
        public_resume.write_bytes(build_resume(resume_content))
    elif not public_resume.is_file():
        raise SystemExit(f"Missing resume PDF: {public_resume}")

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    for filename, html in pages.items():
        (DIST / filename).write_text(html, encoding="utf-8")
    shutil.copyfile(ROOT / "site.css", DIST / "site.css")
    shutil.copyfile(ROOT / "favicon.svg", DIST / "favicon.svg")
    shutil.copyfile(public_resume, DIST / resume_name)
    write_og_png(DIST / "og.png")
    copy_logos(projects)
    (DIST / ".nojekyll").write_text("", encoding="utf-8")
    check(content, pages, DIST / resume_name, DIST / "og.png")
    hidden = sum(1 for project in content["projects"] if not project["show"])
    print(f"Built {len(pages)} pages, {len(projects)} shown, {hidden} hidden, and {resume_name}")


if __name__ == "__main__":
    build()
