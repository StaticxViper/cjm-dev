"""Generate the static portfolio site from portfolio/content.json."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from resume_pdf import build_resume

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
PUBLIC = ROOT / "public"
CONTENT_PATH = ROOT / "content.json"

REQUIRED_IDS = ("about", "experience", "projects", "skills", "education", "contact")


def load_content() -> dict:
    return json.loads(CONTENT_PATH.read_text(encoding="utf-8"))


def esc(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


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


def render_projects(projects: list[dict]) -> str:
    cards = []
    for project in projects:
        link = ""
        if project.get("url"):
            link = (
                f'<a href="{esc(project["url"])}" target="_blank" rel="noopener noreferrer">'
                f'{esc(project["urlLabel"])}<span class="sr-only"> (opens in a new tab)</span></a>'
            )
        cards.append(
            f"""
            <article class="project">
              <h3>{esc(project["name"])}</h3>
              <p>{esc(project["description"])}</p>
              {link}
            </article>
            """
        )
    return "\n".join(cards)


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
                <p class="school-meta">{esc(school["school"])}{location}</p>
                {details}
              </div>
            </article>
            """
        )
    return "\n".join(blocks)


def render_plain_list(items: list[str]) -> str:
    return "<ul class=\"plain-list\">" + "".join(f"<li>{esc(item)}</li>" for item in items) + "</ul>"


def render_page(content: dict) -> str:
    contact = content["contact"]
    resume = esc(content["resumeFile"])
    chips = "".join(f"<li>{esc(item)}</li>" for item in content["credentials"])
    bio = "".join(f"<p>{esc(paragraph)}</p>" for paragraph in content["bio"])
    description = esc(content["bio"][0])
    nav = """
        <ul>
          <li><a href="#about">About</a></li>
          <li><a href="#experience">Experience</a></li>
          <li><a href="#projects">Projects</a></li>
          <li><a href="#skills">Skills</a></li>
          <li><a href="#education">Education</a></li>
          <li><a href="#contact">Contact</a></li>
        </ul>
    """
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(content["preferredName"])} — {esc(content["headline"])}</title>
  <meta name="description" content="{description}">
  <meta name="author" content="{esc(content["name"])}">
  <meta name="theme-color" content="#12312f">
  <link rel="canonical" href="{esc(content["siteUrl"])}">
  <meta property="og:type" content="profile">
  <meta property="og:title" content="{esc(content["name"])} — {esc(content["headline"])}">
  <meta property="og:description" content="{description}">
  <meta property="og:url" content="{esc(content["siteUrl"])}">
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='12' fill='%2312312f'/%3E%3Ctext x='32' y='42' text-anchor='middle' font-family='Georgia' font-size='26' fill='%23f6f3ec'%3ECM%3C/text%3E%3C/svg%3E">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Figtree:wght@400;600;700&amp;family=Fraunces:opsz,wght@9..144,500;9..144,650&amp;display=swap" rel="stylesheet">
  <link rel="stylesheet" href="site.css">
</head>
<body>
  <a class="skip" href="#content">Skip to content</a>
  <header class="site-header">
    <div class="wrap header-inner">
      <a class="brand" href="#about">{esc(content["preferredName"])}</a>
      <button class="nav-toggle" type="button" aria-expanded="false" aria-controls="site-nav">Menu</button>
      <nav id="site-nav" class="site-nav" aria-label="Sections">
        {nav}
      </nav>
      <a class="button button-ink header-resume" href="{resume}" download>Resume</a>
    </div>
  </header>
  <main id="content">
    <div class="wrap">
      <section class="hero" id="about" aria-labelledby="about-heading">
        <p class="eyebrow">{esc(content["employerLine"])}</p>
        <h1 id="about-heading">{esc(content["name"])}</h1>
        <p class="hero-headline">{esc(content["headline"])}</p>
        <p class="hero-location">{esc(content["location"])}</p>
        <div class="bio">{bio}</div>
        <ul class="chips">{chips}</ul>
        <div class="hero-actions">
          <a class="button button-light" href="{resume}" download>Download resume (PDF)</a>
          <a class="button button-ghost" href="mailto:{esc(contact["email"])}">Email {esc(content["preferredName"].split()[0])}</a>
        </div>
      </section>

      <section class="section" id="experience" aria-labelledby="experience-heading">
        <p class="section-index" aria-hidden="true">01</p>
        <h2 id="experience-heading">Experience</h2>
        {render_experience(content["experience"])}
      </section>

      <section class="section" id="projects" aria-labelledby="projects-heading">
        <p class="section-index" aria-hidden="true">02</p>
        <h2 id="projects-heading">Projects</h2>
        <div class="project-grid">
          {render_projects(content["projects"])}
        </div>
      </section>

      <section class="section" id="skills" aria-labelledby="skills-heading">
        <p class="section-index" aria-hidden="true">03</p>
        <h2 id="skills-heading">Skills</h2>
        <div class="skill-grid">
          {render_skills(content["skills"])}
        </div>
      </section>

      <section class="section" id="education" aria-labelledby="education-heading">
        <p class="section-index" aria-hidden="true">04</p>
        <h2 id="education-heading">Education</h2>
        {render_education(content["education"])}
        <div class="subsection note-card">
          <h3>Certifications</h3>
          {render_plain_list(content["certifications"])}
        </div>
        <div class="subsection note-card">
          <h3>Honors</h3>
          {render_plain_list(content["honors"])}
        </div>
      </section>

      <section class="section" id="contact" aria-labelledby="contact-heading">
        <p class="section-index" aria-hidden="true">05</p>
        <h2 id="contact-heading">Contact</h2>
        <ul class="contact-list">
          <li><span>Email</span><a href="mailto:{esc(contact["email"])}">{esc(contact["email"])}</a></li>
          <li><span>Phone</span><a href="{esc(contact["phoneHref"])}">{esc(contact["phone"])}</a></li>
          <li><span>LinkedIn</span><a href="{esc(contact["linkedin"])}" target="_blank" rel="noopener noreferrer">{esc(contact["linkedinLabel"])}<span class="sr-only"> (opens in a new tab)</span></a></li>
          <li><span>GitHub</span><a href="{esc(contact["github"])}" target="_blank" rel="noopener noreferrer">{esc(contact["githubLabel"])}<span class="sr-only"> (opens in a new tab)</span></a></li>
          <li><span>Resume</span><a href="{resume}" download>Download resume (PDF)</a></li>
        </ul>
      </section>
    </div>
  </main>
  <footer class="site-footer">
    <div class="wrap">
      <p>{esc(content["name"])} · {esc(content["headline"])} · {esc(content["location"])}</p>
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


def check(html: str, resume_path: Path) -> None:
    missing = [section_id for section_id in REQUIRED_IDS if f'id="{section_id}"' not in html]
    if missing:
        raise SystemExit(f"Missing sections: {', '.join(missing)}")
    if "Download resume (PDF)" not in html:
        raise SystemExit("Resume download link is missing")
    if not resume_path.is_file() or resume_path.stat().st_size < 1000:
        raise SystemExit("Resume PDF was not written")


def build() -> None:
    content = load_content()
    html = render_page(content)
    resume_name = content["resumeFile"]
    PUBLIC.mkdir(exist_ok=True)
    public_resume = PUBLIC / resume_name
    if content.get("generateResume", True):
        public_resume.write_bytes(build_resume(content))
    elif not public_resume.is_file():
        raise SystemExit(f"Missing resume PDF: {public_resume}")

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()

    (DIST / "index.html").write_text(html, encoding="utf-8")
    shutil.copyfile(ROOT / "site.css", DIST / "site.css")
    shutil.copyfile(public_resume, DIST / resume_name)
    (DIST / ".nojekyll").write_text("", encoding="utf-8")
    check(html, DIST / resume_name)
    print(f"Built {DIST / 'index.html'} and {resume_name}")


if __name__ == "__main__":
    build()
