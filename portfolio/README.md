# Portfolio

Personal portfolio and documentation site for Christopher J. Moulton (CJ Moulton). It is a static site: HTML, one stylesheet, a social preview image, and a resume PDF. There is no backend. The public pages use his name. They describe the work, the roles, and how the projects run.

GitHub Pages publishes the built site at [https://staticxviper.github.io/cjm-dev/](https://staticxviper.github.io/cjm-dev/).

## Update projects

Everything the site can show lives in [`content.json`](content.json), in the `projects` array. Order in that array is the order on the page within each group (Current, Completed, Planned).

Two switches matter:

- `"show": true` publishes the item. `"show": false` keeps the record but leaves it off the site and off the resume PDF.
- `"featured": true` also places a shown item on the home page. A featured item with `"show": false` stays hidden.

`kind` is `website`, `app`, or `script`. `status` is `current`, `completed`, or `planned`. Leave `url` as `""` when there is no link. The page says "Link coming soon" instead of linking nowhere. Leave `logo` as `""` to use a letter monogram. A logo can be a full `https://` address, or a file path under `portfolio/` (for example `public/marks/example.png`).

Copy one of these records, edit it, and put it in the `projects` array.

Website:

```json
{
  "name": "Example site",
  "description": "One sentence about what the site is.",
  "kind": "website",
  "status": "current",
  "show": true,
  "featured": false,
  "tech": "",
  "url": "https://example.com",
  "urlLabel": "Visit site",
  "logo": ""
}
```

App:

```json
{
  "name": "Example app",
  "description": "One sentence about what the app does.",
  "kind": "app",
  "status": "current",
  "show": true,
  "featured": false,
  "tech": "",
  "url": "",
  "urlLabel": "",
  "logo": ""
}
```

Script:

```json
{
  "name": "Example script",
  "description": "One sentence about what the script does.",
  "kind": "script",
  "status": "current",
  "show": true,
  "featured": false,
  "tech": "Python",
  "url": "https://github.com/StaticxViper/cjm-dev/tree/main/scripts/example",
  "urlLabel": "View on GitHub",
  "logo": ""
}
```

Scripts that are already in the file but hidden, including internal tools, can be turned on by setting `"show": true`.

## Update experience

Roles, education, skills, certifications, honors, and the short About copy are in the same file. The resume PDF is built from that experience plus the projects with `"show": true`.

Dates and job titles follow the LinkedIn profile export when it is more specific than the older resume. The LinkedIn export used as a source is stored at [`sources/Profile.pdf`](sources/Profile.pdf). The site does not read that PDF. After a new export, replace the file and update `content.json` to match.

## Update the resume

By default the build writes `portfolio/public/Christopher-Moulton-Resume.pdf` from `content.json`, then copies it into the site. The Resume page links to that file.

To publish a resume you designed yourself:

1. Save it as `portfolio/public/Christopher-Moulton-Resume.pdf`.
2. Set `"generateResume": false` in `content.json` so the next build keeps your file.
3. Run `python portfolio/build.py`.

Set `generateResume` back to `true` if you want the PDF generated from `content.json` again.

## Build

From the repository root:

```bash
python portfolio/build.py
```

Open `portfolio/dist/index.html` and check the other pages, including a narrow window. Commit `content.json`. When the resume is generated, commit the updated PDF in `portfolio/public/` as well.

## Deploy

[`.github/workflows/pages.yml`](../.github/workflows/pages.yml) builds the site and deploys it to GitHub Pages when `main` is pushed. You can also run it by hand from the Actions tab (workflow_dispatch).

The same build publishes the apps hub at `apps/` and the repo map at `repo-map/`. Both are in the site navigation. App notes are authored in [`documentation/apps/`](../documentation/apps/README.md). Source of truth for these pages is cjm-dev; other repos are linked only. A full local preview also renders the map:

```bash
python portfolio/build.py
python scripts/repo_map/generate.py --pages portfolio/dist/repo-map
```

The repository Pages source has to be **GitHub Actions** (Settings → Pages → Build and deployment → Source). The first successful run of this workflow publishes [https://staticxviper.github.io/cjm-dev/](https://staticxviper.github.io/cjm-dev/).
