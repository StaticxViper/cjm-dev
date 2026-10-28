# Repo map

These pages show how the automation scripts call each other. The diagrams under `generated/` are produced from Python `import` statements and in-module function calls. This overview and [data-flow.md](data-flow.md) are written by hand.

Regenerate the diagrams from the repo root:

```bash
python scripts/repo_map/generate.py
python scripts/repo_map/generate.py --check
```

`--check` exits non-zero when `documentation/repo-map/generated/` does not match the current imports. The unit test `unittests/repo_map/test_generate.py` runs that check.

GitHub Pages publishes this folder at <https://staticxviper.github.io/cjm-dev/repo-map/>. [pages.yml](https://github.com/StaticxViper/cjm-dev/blob/main/.github/workflows/pages.yml) builds the personal portfolio and the [apps hub](https://staticxviper.github.io/cjm-dev/apps/), then renders these Markdown files to `portfolio/dist/repo-map/`. Map is a link in the site navigation.

## What each diagram is

- `repo` is one node per tool folder. An arrow means some file in the source folder imports a module in the destination folder.
- The other diagrams start at a tool entry, follow imports two levels, and add arrows for function calls whose target is defined in that set.
- `leadgen.py` loads `leadgen_config.py`, `places_api.py`, `lead_scoring.py`, `lead_pipeline.py`, `lead_persistence.py`, and `leadgen_cli.py` into one module. Calls between those files are drawn as if they share a namespace, which is how they run.

Shared primitives live in `helper_scripts/` (HTTP, HTML signals, names and phones, Maps URLs, CRM JSON-RPC, browser pacing). Tool folders keep their own orchestration.
