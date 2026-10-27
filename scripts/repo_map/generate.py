#!/usr/bin/env python3
"""Generate Mermaid diagrams from Python imports and in-module calls.

Write the diagrams with ``python scripts/repo_map/generate.py``.
``--check`` exits non-zero when ``documentation/repo-map/generated/`` drifts.
``--pages DIR`` writes static HTML in the Moulton site shell. Mermaid loads from a CDN.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GENERATED = REPO / "documentation" / "repo-map" / "generated"
SKIP_DIRS = {"__pycache__", ".venv", "node_modules"}
SCAN_ROOTS = ("scripts", "helper_scripts")
MAX_SCRIPT_FILES = 40
MAX_CALL_EDGES = 80

LEADGEN_PARTS = (
    "scripts/lead_automation/leadgen_config.py",
    "scripts/lead_automation/places_api.py",
    "scripts/lead_automation/lead_scoring.py",
    "scripts/lead_automation/lead_pipeline.py",
    "scripts/lead_automation/lead_persistence.py",
    "scripts/lead_automation/leadgen_cli.py",
)

ENTRIES = {
    "leadgen": ("scripts/lead_automation/leadgen.py",) + LEADGEN_PARTS,
    "enrichers": (
        "scripts/lead_automation/leadenrich.py",
        "scripts/lead_automation/leadenrich_playwright.py",
        "scripts/lead_automation/email_discovery.py",
        "scripts/lead_automation/website_quality.py",
    ),
    "opp-finder": ("scripts/opp_finder_v2/__main__.py",),
    "grocery": ("scripts/grocery/__main__.py",),
    "city-data": ("scripts/city_data/city_data_scraper.py",),
    "zillow": ("scripts/zillow_automation/property_listing_gen.py",),
    "script-manager": ("scripts/script_manager/__main__.py",),
    "actors": (
        "scripts/apify-scripts/google-business/src/main.py",
        "scripts/apify-scripts/city-data/src/main.py",
    ),
}

_SKIP_CALLS = {
    "abs", "all", "any", "bool", "bytearray", "bytes", "callable", "chr",
    "classmethod", "dict", "dir", "divmod", "enumerate", "eval", "exec",
    "filter", "float", "format", "frozenset", "getattr", "globals",
    "hasattr", "hash", "help", "hex", "id", "input", "int", "isinstance",
    "issubclass", "iter", "len", "list", "locals", "map", "max", "min",
    "next", "object", "oct", "open", "ord", "pow", "print", "property",
    "range", "repr", "reversed", "round", "set", "setattr", "slice",
    "sorted", "staticmethod", "str", "sum", "super", "tuple", "type",
    "vars", "zip",
}


def iter_python_files():
    for root_name in SCAN_ROOTS:
        root = REPO / root_name
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            yield path


def as_python_file(candidate: Path) -> Path | None:
    if candidate.suffix == ".py" and candidate.is_file():
        return candidate
    direct = candidate.with_suffix(".py")
    if direct.is_file():
        return direct
    init = candidate / "__init__.py"
    if init.is_file():
        return init
    return None


def resolve_module(module: str | None, level: int, source: Path) -> Path | None:
    if level:
        base = source.parent
        for _ in range(level - 1):
            base = base.parent
        parts = module.split(".") if module else []
        target = base.joinpath(*parts) if parts else base
        return as_python_file(target)
    if not module:
        return None
    parts = module.split(".")
    candidates = [
        REPO.joinpath(*parts),
        REPO.joinpath("scripts", *parts),
        REPO.joinpath("helper_scripts", *parts),
        source.parent.joinpath(*parts),
    ]
    for candidate in candidates:
        found = as_python_file(candidate)
        if found is not None and _in_scan(found):
            return found
    return None


def _in_scan(path: Path) -> bool:
    try:
        rel = path.resolve().relative_to(REPO.resolve())
    except ValueError:
        return False
    return rel.parts and rel.parts[0] in SCAN_ROOTS


def folder_id(path: Path) -> str:
    rel = path.resolve().relative_to(REPO.resolve()).as_posix()
    parts = rel.split("/")
    if parts[0] in SCAN_ROOTS and len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return parts[0]


def parse_file(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeError):
        return None


def imported_files(path: Path, tree: ast.AST) -> list[Path]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                resolved = resolve_module(alias.name, 0, path)
                if resolved is not None:
                    found.append(resolved)
        elif isinstance(node, ast.ImportFrom):
            resolved = resolve_module(node.module, node.level, path)
            if resolved is not None:
                found.append(resolved)
    return found


def _qual_name(class_stack: list[str], name: str) -> str:
    return ".".join([*class_stack, name])


class _Calls(ast.NodeVisitor):
    def __init__(self):
        self.defs: set[str] = set()
        self.calls: list[tuple[str, str]] = []
        self._class: list[str] = []
        self._func: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._class.append(node.name)
        self.generic_visit(node)
        self._class.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        qual = _qual_name(self._class, node.name)
        self.defs.add(qual)
        self._func.append(qual)
        self.generic_visit(node)
        self._func.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        if self._func:
            callee = _callee_name(node.func, self._class)
            if callee and callee not in _SKIP_CALLS:
                self.calls.append((self._func[-1], callee))
        self.generic_visit(node)


def _callee_name(func: ast.expr, class_stack: list[str]) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        if func.value.id in {"logger", "logging"}:
            return None
        if func.value.id == "self" and class_stack:
            return f"{class_stack[-1]}.{func.attr}"
        if func.value.id in {"self", "cls"}:
            return None
        return func.attr if func.attr not in _SKIP_CALLS else None
    return None


def collect_calls(tree: ast.AST) -> tuple[set[str], list[tuple[str, str]]]:
    visitor = _Calls()
    visitor.visit(tree)
    return visitor.defs, visitor.calls


def repo_mermaid(files: list[Path]) -> str:
    edges: set[tuple[str, str]] = set()
    nodes: set[str] = set()
    for path in files:
        tree = parse_file(path)
        if tree is None:
            continue
        source = folder_id(path)
        nodes.add(source)
        for target in imported_files(path, tree):
            dest = folder_id(target)
            nodes.add(dest)
            if dest != source:
                edges.add((source, dest))
    return _flowchart(
        [(node, node) for node in sorted(nodes)],
        sorted(edges),
    )


def _script_files(entry_rels: tuple[str, ...], parsed: dict[Path, ast.AST]) -> list[Path]:
    seeds = []
    for rel in entry_rels:
        path = REPO / rel
        if path.is_file():
            seeds.append(path.resolve())
    seen = set(seeds)
    frontier = list(seeds)
    depth = {path: 0 for path in seeds}
    while frontier and len(seen) < MAX_SCRIPT_FILES:
        current = frontier.pop(0)
        tree = parsed.get(current)
        if tree is None:
            tree = parse_file(current)
            if tree is None:
                continue
            parsed[current] = tree
        if depth[current] >= 2:
            continue
        for target in imported_files(current, tree):
            target = target.resolve()
            if target in seen or not _in_scan(target):
                continue
            seen.add(target)
            depth[target] = depth[current] + 1
            frontier.append(target)
            if len(seen) >= MAX_SCRIPT_FILES:
                break
    return sorted(seen, key=lambda item: item.as_posix().lower())


def script_mermaid(entry_rels: tuple[str, ...]) -> str:
    parsed: dict[Path, ast.AST] = {}
    files = _script_files(entry_rels, parsed)
    leadgen = {(REPO / rel).resolve() for rel in LEADGEN_PARTS}
    defs: dict[Path, set[str]] = {}
    raw_calls: dict[Path, list[tuple[str, str]]] = {}
    import_edges: set[tuple[str, str]] = set()
    labels: dict[str, str] = {}
    seen_ids: set[str] = set()
    for path in files:
        tree = parsed.get(path) or parse_file(path)
        if tree is None:
            continue
        parsed[path] = tree
        file_defs, calls = collect_calls(tree)
        defs[path] = file_defs
        raw_calls[path] = calls
        rel = path.relative_to(REPO.resolve()).as_posix()
        labels[rel] = rel
        seen_ids.add(rel)
        for target in imported_files(path, tree):
            target = target.resolve()
            if target not in files:
                continue
            dest = target.relative_to(REPO.resolve()).as_posix()
            if dest != rel:
                import_edges.add((rel, dest))
                labels[dest] = dest

    owners: dict[str, set[Path]] = {}
    for path, names in defs.items():
        for name in names:
            owners.setdefault(name, set()).add(path)

    def owner_of(caller: Path, name: str) -> Path | None:
        if name in defs.get(caller, ()):
            return caller
        if caller in leadgen:
            for path in leadgen:
                if name in defs.get(path, ()):
                    return path
        found = owners.get(name) or set()
        if len(found) == 1:
            return next(iter(found))
        return None

    call_edges: list[tuple[str, str, str, str]] = []
    for path, calls in raw_calls.items():
        caller_rel = path.relative_to(REPO.resolve()).as_posix()
        for caller, callee in calls:
            if callee in _SKIP_CALLS or callee.startswith("_"):
                continue
            dest = owner_of(path, callee)
            if dest is None:
                continue
            dest_rel = dest.relative_to(REPO.resolve()).as_posix()
            call_edges.append((caller_rel, caller, dest_rel, callee))

    call_edges = sorted(set(call_edges))
    truncated = len(call_edges) > MAX_CALL_EDGES
    # Prefer cross-file calls when the cap bites.
    call_edges.sort(key=lambda item: (item[0] == item[2], item[0], item[1], item[3]))
    call_edges = call_edges[:MAX_CALL_EDGES]

    edges = []
    for src, dest in sorted(import_edges):
        edges.append((src, dest))
        seen_ids.add(src)
        seen_ids.add(dest)
    for src_file, caller, dest_file, callee in call_edges:
        src_id = f"{src_file}:{caller}"
        dest_id = f"{dest_file}:{callee}"
        labels[src_id] = caller
        labels[dest_id] = callee
        edges.append((src_id, dest_id))
        seen_ids.add(src_id)
        seen_ids.add(dest_id)
    for rel in labels:
        if rel in seen_ids or rel in import_edges:
            continue
    nodes = [(node_id, labels.get(node_id, node_id)) for node_id in sorted(seen_ids)]
    chart = _flowchart(nodes, edges)
    if truncated:
        chart += f"\n%% call edges capped at {MAX_CALL_EDGES}\n"
    return chart


def _flowchart(nodes: list[tuple[str, str]], edges: list[tuple[str, str]]) -> str:
    ids = {}
    lines = ["flowchart LR"]
    for node_id, label in nodes:
        slug = _slug(node_id)
        base = slug
        counter = 2
        while slug in ids.values():
            slug = f"{base}_{counter}"
            counter += 1
        ids[node_id] = slug
        lines.append(f'  {slug}["{_label(label)}"]')
    for src, dest in edges:
        if src not in ids or dest not in ids:
            continue
        lines.append(f"  {ids[src]} --> {ids[dest]}")
    if len(lines) == 1:
        lines.append('  empty["no internal edges"]')
    return "\n".join(lines) + "\n"


def _slug(value: str) -> str:
    chars = []
    for char in value:
        chars.append(char if char.isalnum() else "_")
    slug = "".join(chars).strip("_")
    if not slug or slug[0].isdigit():
        slug = f"n_{slug}"
    return slug[:90]


def _label(value: str) -> str:
    return value.replace("\\", "/").replace('"', "'").replace("[", "(").replace("]", ")")


def generated_documents() -> dict[str, str]:
    files = sorted(iter_python_files(), key=lambda item: item.as_posix().lower())
    documents = {
        "repo.md": _document(
            "Repository modules",
            "Folder-level imports under scripts/ and helper_scripts/.",
            repo_mermaid(files),
        )
    }
    titles = {
        "leadgen": "Lead generation",
        "enrichers": "Lead enrichers",
        "opp-finder": "Opportunity finder",
        "grocery": "Grocery",
        "city-data": "City data",
        "zillow": "Zillow",
        "script-manager": "Script Manager",
        "actors": "Apify Actors",
    }
    for key, entry in ENTRIES.items():
        documents[f"{key}.md"] = _document(
            titles[key],
            "Imports followed two levels from the entry, plus in-module calls.",
            script_mermaid(entry),
        )
    return documents


def _document(title: str, note: str, chart: str) -> str:
    return (
        f"# {title}\n\n"
        f"{note} Generated by `scripts/repo_map/generate.py`. Do not edit by hand.\n\n"
        f"```mermaid\n{chart}```\n"
    )


def check(directory: Path | None = None) -> list[str]:
    """Return drift messages. An empty list means the generated files match."""
    directory = directory or GENERATED
    expected = generated_documents()
    errors = []
    if not directory.is_dir():
        return [f"missing directory {directory.relative_to(REPO).as_posix()}"]
    for name, content in sorted(expected.items()):
        path = directory / name
        if not path.is_file():
            errors.append(f"missing {name}")
            continue
        current = path.read_text(encoding="utf-8")
        if current != content:
            errors.append(f"drift {name}")
    extras = sorted(
        path.name
        for path in directory.glob("*.md")
        if path.name not in expected
    )
    errors.extend(f"unexpected {name}" for name in extras)
    return errors


def write_generated(directory: Path | None = None) -> None:
    directory = directory or GENERATED
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in generated_documents().items():
        (directory / name).write_text(content, encoding="utf-8")
    for path in directory.glob("*.md"):
        if path.name not in generated_documents():
            path.unlink()


def write_pages(dest: Path) -> None:
    """Render overview, data-flow, and generated diagrams in the site shell."""
    import sys

    sys.path.insert(0, str(REPO / "portfolio"))
    from pages_shell import SOURCE_NOTE, esc, load_content, markdown_to_html, render_site_page

    content = load_content()
    dest.mkdir(parents=True, exist_ok=True)
    entries: list[tuple[str, str, str]] = []
    for filename, title in (("overview.md", "Overview"), ("data-flow.md", "Data flow")):
        source = REPO / "documentation" / "repo-map" / filename
        text = source.read_text(encoding="utf-8")
        entries.append((filename.replace(".md", ".html"), title, text))
    for path in sorted(GENERATED.glob("*.md")):
        title = path.stem.replace("-", " ").title()
        entries.append((path.name.replace(".md", ".html"), title, path.read_text(encoding="utf-8")))

    items = "\n".join(
        f'<li><a href="{esc(html_name)}">{esc(title)}</a></li>'
        for html_name, title, _text in entries
    )
    index_body = f"""
      <header class="page-intro">
        <p class="eyebrow">Map</p>
        <h1>Repo map</h1>
        <p class="lede">Import and call diagrams for the code in this repo.</p>
        <p class="truth">{esc(SOURCE_NOTE)}</p>
        <p class="work-link"><a href="../apps/index.html">Apps hub</a></p>
      </header>
      <section class="section" aria-labelledby="diagrams-heading">
        <h2 id="diagrams-heading">Diagrams</h2>
        <ul class="plain-list">
          {items}
        </ul>
      </section>
    """
    (dest / "index.html").write_text(
        render_site_page(
            content,
            title="Repo map — Moulton",
            description="Import and call diagrams for the code in cjm-dev.",
            canonical_path="repo-map/index.html",
            body=index_body,
            active="map",
            depth=1,
        ),
        encoding="utf-8",
    )
    for html_name, title, text in entries:
        links = []
        for name, label, _text in entries:
            current = ' aria-current="page"' if name == html_name else ""
            links.append(f'<a href="{esc(name)}"{current}>{esc(label)}</a>')
        body = (
            f'<nav class="layer-nav" aria-label="Diagrams">{"".join(links)}</nav>'
            f'<div class="prose">{markdown_to_html(text, depth=1)}</div>'
        )
        (dest / html_name).write_text(
            render_site_page(
                content,
                title=f"{title} — Repo map — Moulton",
                description=f"{title} diagram for the cjm-dev repo map.",
                canonical_path=f"repo-map/{html_name}",
                body=body,
                active="map",
                depth=1,
                mermaid="```mermaid" in text,
            ),
            encoding="utf-8",
        )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--check" in args:
        errors = check()
        for error in errors:
            print(error)
        return 1 if errors else 0
    if "--pages" in args:
        dest = Path(args[args.index("--pages") + 1])
        if not dest.is_absolute():
            dest = REPO / dest
        write_pages(dest)
        return 0
    write_generated()
    print(f"wrote {GENERATED.relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
