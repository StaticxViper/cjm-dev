# Apps hub

Plain-English pages for each project, published with the personal portfolio.

Source of truth for these pages is cjm-dev; other repos are linked only.

Live pages: <https://staticxviper.github.io/cjm-dev/apps/>

The hub has three layers:

- **Map** — generated diagrams in [`documentation/repo-map/`](../repo-map/overview.md), published at `repo-map/`.
- **How it works** — what the product does now. No history dump and no function-by-function reference.
- **Changelog** — short dated notes when behavior changes.

ADRs are optional and only for a decision that is hard to reverse. When one is needed, add `documentation/apps/<slug>/decisions/`. That folder is not published until a page is written for it.

## Add a project

1. Add an object to [`catalog.json`](catalog.json). `slug` is the folder name. `code` is `this-repo`, `external`, or `unrecorded`.
2. Create `documentation/apps/<slug>/HOW_IT_WORKS.md` and `CHANGELOG.md`.
3. Link diagrams with site paths such as `repo-map/data-flow.html`. In the Markdown, prefix a site path with `site:` so the build can place it: `[Data flow](site:repo-map/data-flow.html)`.
4. For an external repo, set `github.owner`, `github.name`, and an `https://github.com/...` URL. That is a reference only.

Do not add a git remote, a submodule, or a copy of another repo. When a project's behavior changes, including a Lovable publish, update that project's How it works page and Changelog in cjm-dev in the same documentation change.

`portfolioName` matches a `name` in [`portfolio/content.json`](../../portfolio/content.json) when the public project card should link here.

## Build

From the repo root, the portfolio build renders this folder into `portfolio/dist/apps/`:

```bash
python portfolio/build.py
python scripts/repo_map/generate.py --pages portfolio/dist/repo-map
```

[`.github/workflows/pages.yml`](../../.github/workflows/pages.yml) runs both steps.
