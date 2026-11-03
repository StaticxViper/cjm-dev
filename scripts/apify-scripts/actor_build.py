"""Build and smoke-test the Apify Actors in this folder.

Each Actor folder is its own Docker build context. Apify rejects a context
outside the Actor directory, so the repo modules an Actor imports are copied
into ``<actor>/platform_bundle/`` from the list in ``<actor>/bundle.txt``.
The copies are committed so ``apify push`` works from the Actor directory.

Commands (run from anywhere in the repo):

    python scripts/apify-scripts/actor_build.py bundle [ACTOR ...]
    python scripts/apify-scripts/actor_build.py check [ACTOR ...]
    python scripts/apify-scripts/actor_build.py budgets
    python scripts/apify-scripts/actor_build.py isolate ACTOR
    python scripts/apify-scripts/actor_build.py probe --actor-dir DIR [--repo DIR]
    python scripts/apify-scripts/actor_build.py smoke ACTOR [--image TAG] [--platform]

``check`` fails on bundle drift, a Dockerfile or actor.json that reaches
outside the Actor folder, an unbounded input-schema limit, or a budget that
does not fit the Actor's memory and timeout settings. ``smoke`` runs
``fixtures/INPUT.json`` and fails when the run does not succeed or goes over
``fixtures/budget.json``. Standard library only, except ``--platform``, which
needs ``apify-client`` and ``APIFY_TOKEN``.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BUNDLE_DIR = "platform_bundle"
MANIFEST = "bundle.txt"
BUDGET = Path("fixtures") / "budget.json"
FIXTURE = Path("fixtures") / "INPUT.json"
README_BEGIN = "<!-- budgets:begin -->"
README_END = "<!-- budgets:end -->"
BUDGET_KEYS = {
    "memoryMbytes",
    "maxDurationSecs",
    "minItems",
    "maxItems",
    "maxChargeUsd",
    "maxUsageUsd",
    "notes",
}
# Paths an Actor's own code adds to sys.path, relative to the repo root.
SEARCH_DIRS = (
    "",
    "scripts",
    "scripts/city_data",
    "scripts/lead_automation",
    "scripts/zillow_automation",
)


def actor_dirs(names=None):
    found = sorted(
        path.parent for path in HERE.glob(f"*/{MANIFEST}") if (path.parent / ".actor").is_dir()
    )
    if not names:
        return found
    by_name = {path.name: path for path in found}
    missing = [name for name in names if name not in by_name]
    if missing:
        raise SystemExit(f"Unknown Actor folder: {', '.join(missing)}")
    return [by_name[name] for name in names]


def _manifest_lines(actor):
    for line in (actor / MANIFEST).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            yield line


def read_manifest(actor):
    return [line for line in _manifest_lines(actor) if not line.startswith("!")]


def unbundled_imports(actor):
    """``!module`` lines: imports only reached by the local CLI, left out on purpose."""
    return {line[1:].strip() for line in _manifest_lines(actor) if line.startswith("!")}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def bundle(actor):
    target = actor / BUNDLE_DIR
    if target.exists():
        shutil.rmtree(target)
    files = read_manifest(actor)
    for relative in files:
        source = REPO / relative
        if not source.is_file():
            raise SystemExit(f"{actor.name}/{MANIFEST}: missing {relative}")
        dest = target / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
    return len(files)


def _bundled_files(actor):
    root = actor / BUNDLE_DIR
    if not root.is_dir():
        return set()
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }


def drift_errors(actor):
    errors = []
    files = read_manifest(actor)
    if len(files) != len(set(files)):
        errors.append(f"{MANIFEST} lists a path twice")
    bundled = _bundled_files(actor)
    for relative in files:
        source = REPO / relative
        if not source.is_file():
            errors.append(f"{MANIFEST} lists {relative}, which does not exist")
            continue
        if relative not in bundled:
            errors.append(f"{BUNDLE_DIR}/{relative} is missing")
        elif source.read_bytes() != (actor / BUNDLE_DIR / relative).read_bytes():
            errors.append(f"{BUNDLE_DIR}/{relative} differs from {relative}")
    for extra in sorted(bundled - set(files)):
        errors.append(f"{BUNDLE_DIR}/{extra} is not listed in {MANIFEST}")
    return errors


def build_errors(actor):
    errors = []
    config = read_json(actor / ".actor" / "actor.json")
    context = config.get("dockerContextDir")
    if context not in (None, ".."):
        errors.append(f"actor.json dockerContextDir is {context!r}; omit it so the Actor folder is the context")
    if config.get("dockerfile", "../Dockerfile") != "../Dockerfile":
        errors.append("actor.json dockerfile must be ../Dockerfile")
    dockerfile = (actor / "Dockerfile").read_text(encoding="utf-8")
    if "ACTOR_PATH_IN_DOCKER_CONTEXT" in dockerfile:
        errors.append("Dockerfile uses ACTOR_PATH_IN_DOCKER_CONTEXT")
    for number, line in enumerate(dockerfile.splitlines(), 1):
        parts = line.split()
        if not parts or parts[0].upper() not in ("COPY", "ADD"):
            continue
        sources = [part for part in parts[1:-1] if not part.startswith("--")]
        for source in sources:
            if source.startswith(("..", "/")) or source.split("/")[0] in ("scripts", "helper_scripts"):
                errors.append(f"Dockerfile line {number} copies {source} from outside the Actor folder")
    if not (actor / ".dockerignore").is_file():
        errors.append(".dockerignore is missing")
    return errors


def schema_errors(actor):
    """Store users get schema defaults. A limit with no default or ceiling can start a huge job."""
    errors = []
    schema = read_json(actor / ".actor" / "input_schema.json")
    for name, prop in schema.get("properties", {}).items():
        kind = prop.get("type")
        if kind == "integer" and name.lower().startswith("max"):
            if "default" not in prop:
                errors.append(f"input {name} has no default")
            if "maximum" not in prop:
                errors.append(f"input {name} has no maximum")
            elif "default" in prop and prop["default"] > prop["maximum"]:
                errors.append(f"input {name} default is above its maximum")
        if kind == "array" and not (prop.get("items") or {}).get("enum") and "maxItems" not in prop:
            errors.append(f"input {name} is a free-form list with no maxItems")
    return errors


def load_budget(actor):
    path = actor / BUDGET
    if not path.is_file():
        raise ValueError(f"{BUDGET.as_posix()} is missing")
    budget = read_json(path)
    unknown = set(budget) - BUDGET_KEYS
    if unknown:
        raise ValueError(f"{BUDGET.as_posix()} has unknown keys: {', '.join(sorted(unknown))}")
    for key in ("memoryMbytes", "maxDurationSecs", "minItems", "maxItems", "maxChargeUsd"):
        if key not in budget:
            raise ValueError(f"{BUDGET.as_posix()} needs {key}")
    return budget


def budget_errors(actor):
    try:
        budget = load_budget(actor)
    except ValueError as error:
        return [str(error)]
    errors = []
    config = read_json(actor / ".actor" / "actor.json")
    memory = budget["memoryMbytes"]
    if memory < 128 or memory & (memory - 1):
        errors.append("budget memoryMbytes must be a power of two, 128 or more")
    low = config.get("minMemoryMbytes", 128)
    high = config.get("maxMemoryMbytes", 32768)
    if not low <= memory <= high:
        errors.append(f"budget memoryMbytes {memory} is outside actor.json {low}-{high}")
    timeout = (config.get("defaultRunOptions") or {}).get("timeoutSecs")
    if timeout and budget["maxDurationSecs"] > timeout:
        errors.append(f"budget maxDurationSecs is above actor.json defaultRunOptions.timeoutSecs {timeout}")
    if budget["minItems"] > budget["maxItems"]:
        errors.append("budget minItems is above maxItems")
    fixture = read_json(actor / FIXTURE)
    spend = fixture.get("maxSpendUsd")
    if spend is not None and budget["maxChargeUsd"] > spend:
        errors.append("budget maxChargeUsd is above the fixture maxSpendUsd")
    return errors


def budget_table():
    rows = [
        "| Actor | Memory (MB) | Max duration (s) | Dataset rows | Max PPE charge (USD) | Max platform usage (USD) |",
        "|-------|-------------|------------------|--------------|----------------------|--------------------------|",
    ]
    for actor in actor_dirs():
        if actor.name.startswith("_"):
            continue
        budget = load_budget(actor)
        usage = budget.get("maxUsageUsd")
        rows.append(
            f"| `{actor.name}` | {budget['memoryMbytes']} | {budget['maxDurationSecs']} | "
            f"{budget['minItems']}-{budget['maxItems']} | {budget['maxChargeUsd']} | "
            f"{'—' if usage is None else usage} |"
        )
    return "\n".join(rows)


def readme_errors():
    text = (HERE / "README.md").read_text(encoding="utf-8")
    if README_BEGIN not in text or README_END not in text:
        return [f"README.md is missing the {README_BEGIN} block"]
    current = text.split(README_BEGIN, 1)[1].split(README_END, 1)[0].strip()
    if current != budget_table():
        return ["README.md budget table is stale. Run: python scripts/apify-scripts/actor_build.py budgets --write"]
    return []


def write_readme_table():
    path = HERE / "README.md"
    text = path.read_text(encoding="utf-8")
    head, rest = text.split(README_BEGIN, 1)
    _, tail = rest.split(README_END, 1)
    path.write_text(f"{head}{README_BEGIN}\n{budget_table()}\n{README_END}{tail}", encoding="utf-8")


def check(actors):
    failed = False
    for actor in actors:
        errors = drift_errors(actor) + build_errors(actor) + schema_errors(actor) + budget_errors(actor)
        for error in errors:
            print(f"{actor.name}: {error}")
        failed = failed or bool(errors)
    for error in readme_errors():
        print(error)
        failed = True
    if failed:
        print("Fix the list above. Run `actor_build.py bundle` after a shared module changes.")
        return 1
    print(f"OK: {len(actors)} Actor folders are self-contained and inside their budgets.")
    return 0


# --- import probe -----------------------------------------------------------


def _guarded(node, parents):
    """True when an import sits in try/except ImportError or under TYPE_CHECKING."""
    for parent in parents:
        if isinstance(parent, ast.Try) and node in _try_body_nodes(parent):
            for handler in parent.handlers:
                names = _handler_names(handler)
                if not names or names & {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}:
                    return True
        if isinstance(parent, ast.If) and "TYPE_CHECKING" in ast.unparse(parent.test):
            return True
    return False


def _try_body_nodes(node):
    return {child for stmt in node.body for child in ast.walk(stmt)}


def _handler_names(handler):
    if handler.type is None:
        return set()
    items = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return {ast.unparse(item).split(".")[-1] for item in items}


def collect_imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = set()

    def visit(node, parents):
        if isinstance(node, (ast.Import, ast.ImportFrom)) and not _guarded(node, parents):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif node.level == 0 and node.module:
                found.add(node.module)
        for child in ast.iter_child_nodes(node):
            visit(child, parents + [node])

    visit(tree, [])
    return found


def repo_module_names(root):
    names = set()
    for relative in SEARCH_DIRS:
        folder = root / relative
        if not folder.is_dir():
            continue
        for entry in folder.iterdir():
            if entry.suffix == ".py":
                names.add(entry.stem)
            elif entry.is_dir() and (entry / "__init__.py").is_file():
                names.add(entry.name)
    return names - {"src", "runtime"}


def probe(actor_dir, repo=None, strict=False):
    """Import every module the Actor's code and bundle name, from the bundle only."""
    actor_dir = Path(actor_dir).resolve()
    bundle_root = Path(os.environ.get("CJM_REPO_ROOT") or actor_dir / BUNDLE_DIR).resolve()
    os.environ["CJM_REPO_ROOT"] = str(bundle_root)
    os.chdir(actor_dir)
    sys.path.insert(0, str(actor_dir))
    known = repo_module_names(Path(repo).resolve()) if repo else repo_module_names(bundle_root)
    sources = sorted((actor_dir / "src").rglob("*.py")) + sorted(bundle_root.rglob("*.py"))
    wanted = set()
    for path in sources:
        wanted |= collect_imports(path)
    skipped = unbundled_imports(actor_dir) if (actor_dir / MANIFEST).is_file() else set()
    wanted = {name for name in wanted if name.split(".")[0] not in skipped}

    import importlib

    failures = []
    for name in ["src.runtime"] + sorted(
        f"src.{path.relative_to(actor_dir / 'src').with_suffix('').as_posix().replace('/', '.')}"
        for path in (actor_dir / "src").rglob("*.py")
        if path.name != "__main__.py"
    ):
        try:
            importlib.import_module(name.removesuffix(".__init__"))
        except Exception as error:  # noqa: BLE001 - report every broken module
            failures.append(f"{name}: {type(error).__name__}: {error}")
    runtime = sys.modules.get("src.runtime")
    if runtime is not None:
        runtime.prepare_imports()
    for name in sorted(wanted):
        if name.split(".")[0] in ("src", "runtime"):
            continue
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as error:
            missing = (error.name or name).split(".")[0]
            if missing in known or strict:
                failures.append(f"import {name}: {error}")
        except Exception as error:  # noqa: BLE001
            failures.append(f"import {name}: {type(error).__name__}: {error}")
    if repo:
        repo_root = Path(repo).resolve()
        interpreter = {Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()}
        for name, module in list(sys.modules.items()):
            location = getattr(module, "__file__", None)
            if not location or name == "__main__":
                continue
            path = Path(location).resolve()
            if "site-packages" in path.parts or any(path.is_relative_to(prefix) for prefix in interpreter):
                continue
            if path.is_relative_to(repo_root):
                failures.append(f"{module.__name__} loaded from the repo, not the bundle: {path}")
    for failure in failures:
        print(f"FAIL {failure}")
    if failures:
        print(f"Add the missing files to {MANIFEST} and run `actor_build.py bundle`.")
        return 1
    print(f"OK: {len(wanted)} imports resolve from {bundle_root}")
    return 0


def _docker_context_files(actor, dest):
    ignore = [
        line.strip().rstrip("/")
        for line in (actor / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]

    def skip(directory, names):
        rel = Path(directory).relative_to(actor)
        dropped = []
        for name in names:
            path = (rel / name).as_posix().removeprefix("./")
            if any(Path(path).match(pattern.removeprefix("**/")) or path == pattern for pattern in ignore):
                dropped.append(name)
        return dropped

    shutil.copytree(actor, dest, ignore=skip)


def isolate(actor):
    """Copy the build context to a temp folder and probe it outside the repo."""
    with tempfile.TemporaryDirectory(prefix=f"actor-{actor.name}-") as tmp:
        dest = Path(tmp) / actor.name
        _docker_context_files(actor, dest)
        env = dict(os.environ, CJM_REPO_ROOT=str(dest / BUNDLE_DIR))
        env.pop("PYTHONPATH", None)
        command = [sys.executable, str(Path(__file__).resolve()), "probe", "--actor-dir", str(dest), "--repo", str(REPO)]
        return subprocess.run(command, env=env, cwd=tmp).returncode


# --- fixture smoke ----------------------------------------------------------


def evaluate(budget, result):
    """Return the budget violations for a finished run."""
    problems = []
    if result["status"] != "SUCCEEDED":
        problems.append(f"status {result['status']} (want SUCCEEDED)")
    memory = result.get("memoryMaxMbytes")
    if memory is not None and memory > budget["memoryMbytes"]:
        problems.append(f"peak memory {memory:.0f} MB > {budget['memoryMbytes']} MB")
    if result["durationSecs"] > budget["maxDurationSecs"]:
        problems.append(f"duration {result['durationSecs']:.0f}s > {budget['maxDurationSecs']}s")
    items = result["itemCount"]
    if not budget["minItems"] <= items <= budget["maxItems"]:
        problems.append(f"dataset rows {items} outside {budget['minItems']}-{budget['maxItems']}")
    if result["chargeUsd"] > Decimal(str(budget["maxChargeUsd"])):
        problems.append(f"PPE charge ${result['chargeUsd']} > ${budget['maxChargeUsd']}")
    usage = result.get("usageUsd")
    if usage is not None and budget.get("maxUsageUsd") is not None and usage > budget["maxUsageUsd"]:
        problems.append(f"platform usage ${usage:.4f} > ${budget['maxUsageUsd']}")
    return problems


def ppe_prices(actor):
    events = read_json(actor / ".actor" / "pay_per_event.json").get("actorChargeEvents", {})
    return {name: Decimal(str(event.get("eventPriceUsd", 0))) for name, event in events.items()}


def _parse_mem(text):
    value = text.split("/")[0].strip()
    units = {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024, "kB": 1 / 1000, "MB": 1, "GB": 1000, "B": 1 / 1048576}
    for unit, scale in units.items():
        if value.endswith(unit):
            return float(value[: -len(unit)]) * scale
    return 0.0


def _records(folder):
    return [path for path in sorted(folder.glob("*.json")) if not path.name.startswith("__")]


def count_items(storage):
    return len(_records(storage / "datasets" / "default"))


def read_charging_log(storage):
    """Sum the local SDK charging log. Returns (total USD, {event: count})."""
    charge = Decimal()
    charged = {}
    for path in _records(storage / "datasets" / "charging-log"):
        row = read_json(path)
        event = str(row.get("event_name", ""))
        # apify-* events are synthetic per-row events; these Actors do not bill per dataset item.
        if event.startswith("apify-"):
            continue
        count = int(row.get("charged_count", 1))
        charged[event] = charged.get(event, 0) + count
        charge += Decimal(str(row.get("event_price_usd", 0))) * count
    return charge, charged


def _docker(*args, check=True, capture=True):
    try:
        return subprocess.run(["docker", *args], check=check, capture_output=capture, text=True)
    except subprocess.CalledProcessError as error:
        if error.stdout:
            print(error.stdout, file=sys.stderr)
        if error.stderr:
            print(error.stderr, file=sys.stderr)
        raise


def _host_owner():
    """Numeric uid:gid of this process. Missing on Windows, where Docker Desktop owns the mount."""
    getuid = getattr(os, "getuid", None)
    getgid = getattr(os, "getgid", None)
    if getuid is None or getgid is None:
        return None
    return f"{getuid()}:{getgid()}"


def _chown_tree(image, folder, owner):
    """Give the storage mount to the container user, then back to the host so the temp dir can be removed."""
    result = _docker(
        "run", "--rm", "--user", "0", "--entrypoint", "chown",
        "-v", f"{folder}:/storage",
        image, "-R", owner, "/storage",
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        print(f"chown {owner} {folder} failed ({result.returncode}): {detail}", file=sys.stderr)


def _empty_result(status):
    return {
        "status": status,
        "durationSecs": 0.0,
        "memoryMaxMbytes": None,
        "itemCount": 0,
        "chargeUsd": Decimal("0"),
        "chargedEvents": {},
    }


def smoke_docker(actor, budget, image):
    if image is None:
        image = f"cjm-actor-{actor.name}:smoke"
        print(f"Building {image} from {actor}")
        _docker("build", "-t", image, str(actor), capture=False)
    events = read_json(actor / ".actor" / "pay_per_event.json").get("actorChargeEvents", {})
    pricing = {"pricingModel": "PAY_PER_EVENT", "pricingPerEvent": {"actorChargeEvents": events}}
    name = f"smoke-{actor.name}-{os.getpid()}"
    with tempfile.TemporaryDirectory(prefix=f"smoke-{actor.name}-", ignore_cleanup_errors=True) as tmp:
        storage = Path(tmp) / "storage"
        kvs = storage / "key_value_stores" / "default"
        kvs.mkdir(parents=True)
        shutil.copyfile(actor / FIXTURE, kvs / "INPUT.json")
        host = _host_owner()
        if host:
            _chown_tree(image, storage, "myuser:myuser")
        memory = budget["memoryMbytes"]
        peak = [0.0]
        done = threading.Event()
        watcher = None
        started = time.monotonic()
        timed_out = False
        state = {}
        logs = None
        start_error = None
        try:
            try:
                _docker(
                    "run", "-d", "--name", name,
                    f"--memory={memory}m", f"--memory-swap={memory}m", "--shm-size=512m",
                    "-v", f"{storage}:/home/myuser/storage",
                    "-e", "APIFY_LOCAL_STORAGE_DIR=/home/myuser/storage",
                    "-e", "CRAWLEE_STORAGE_DIR=/home/myuser/storage",
                    "-e", "ACTOR_TEST_PAY_PER_EVENT=true",
                    "-e", f"APIFY_ACTOR_PRICING_INFO={json.dumps(pricing)}",
                    # The SDK reads an empty object as unset and then ignores the pricing info.
                    "-e", f"APIFY_CHARGED_ACTOR_EVENT_COUNTS={json.dumps({event: 0 for event in events})}",
                    image,
                )
            except subprocess.CalledProcessError as error:
                start_error = error
            else:
                def watch():
                    while not done.is_set():
                        out = _docker("stats", "--no-stream", "--format", "{{.MemUsage}}", name, check=False)
                        if out.returncode == 0 and out.stdout.strip():
                            peak[0] = max(peak[0], _parse_mem(out.stdout))
                        done.wait(1)

                watcher = threading.Thread(target=watch, daemon=True)
                watcher.start()
                while True:
                    running = _docker("inspect", "-f", "{{.State.Running}}", name, check=False)
                    if running.returncode != 0 or running.stdout.strip() != "true":
                        break
                    if time.monotonic() - started > budget["maxDurationSecs"]:
                        timed_out = True
                        _docker("kill", name, check=False)
                        break
                    time.sleep(1)
        finally:
            done.set()
            if watcher is not None:
                watcher.join(timeout=5)
            inspected = _docker("inspect", "-f", "{{json .State}}", name, check=False)
            if inspected.returncode == 0 and inspected.stdout.strip():
                try:
                    state = json.loads(inspected.stdout)
                except json.JSONDecodeError:
                    state = {}
            logs = _docker("logs", "--tail", "60", name, check=False)
            _docker("rm", "-f", name, check=False)
            if host:
                _chown_tree(image, storage, host)
        duration = time.monotonic() - started
        exit_code = state.get("ExitCode")
        if exit_code is None and start_error is not None:
            exit_code = start_error.returncode
        if timed_out:
            status = "TIMED-OUT"
        elif state.get("OOMKilled"):
            status = "FAILED (out of memory)"
        elif exit_code == 0:
            status = "SUCCEEDED"
        else:
            status = f"FAILED (exit {exit_code})"
        charge, charged = read_charging_log(storage)
        result = {
            "status": status,
            "durationSecs": duration,
            "memoryMaxMbytes": peak[0] or None,
            "itemCount": count_items(storage),
            "chargeUsd": charge,
            "chargedEvents": charged,
        }
        unknown = sorted(set(charged) - set(ppe_prices(actor)))
        if unknown:
            print(f"Charged events not in pay_per_event.json (priced $1 locally): {', '.join(unknown)}")
        log_text = ""
        if logs is not None:
            log_text = (logs.stdout or "") + (logs.stderr or "")
        if start_error is not None and not log_text.strip():
            log_text = (start_error.stderr or start_error.stdout or str(start_error)).strip()
        return result, log_text


def smoke_platform(actor, budget, actor_id=None, build=None):
    from apify_client import ApifyClient

    token = os.environ.get("APIFY_TOKEN")
    if not token:
        raise SystemExit("Set APIFY_TOKEN for a platform smoke run.")
    client = ApifyClient(token)
    if not actor_id:
        username = client.user("me").get()["username"]
        actor_id = f"{username}/{read_json(actor / '.actor' / 'actor.json')['name']}"
    print(f"Running {actor_id} on Apify with {FIXTURE.as_posix()}")
    # The charge cap is above the budget so an overrun is measured, not hidden.
    cap = Decimal(str(budget["maxChargeUsd"])) * 2 + Decimal("0.01")
    run = client.actor(actor_id).call(
        run_input=read_json(actor / FIXTURE),
        build=build,
        memory_mbytes=budget["memoryMbytes"],
        timeout_secs=budget["maxDurationSecs"],
        max_total_charge_usd=cap,
    )
    if run is None:
        raise SystemExit("The run did not finish.")
    run = client.run(run["id"]).get()
    stats = run.get("stats") or {}
    prices = ppe_prices(actor)
    charged = run.get("chargedEventCounts") or {}
    charge = sum((prices.get(event, Decimal()) * count for event, count in charged.items()), Decimal())
    dataset = client.dataset(run["defaultDatasetId"]).get() or {}
    result = {
        "status": run["status"],
        "durationSecs": float(stats.get("runTimeSecs") or 0),
        "memoryMaxMbytes": (stats.get("memMaxBytes") or 0) / 1048576 or None,
        "itemCount": int(dataset.get("itemCount") or 0),
        "chargeUsd": charge,
        "chargedEvents": charged,
        "usageUsd": run.get("usageTotalUsd"),
        "runUrl": f"https://console.apify.com/actors/runs/{run['id']}",
    }
    log = client.log(run["id"]).get() or ""
    return result, "\n".join(log.splitlines()[-60:])


def _write_report(report, actor, result, problems, log):
    path = Path(report)
    payload = dict(result, chargeUsd=str(result["chargeUsd"]), actor=actor.name, problems=problems)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    path.with_suffix(".log").write_text(log or "", encoding="utf-8")


def smoke(actor, image=None, platform=False, actor_id=None, build=None, report=None):
    budget = load_budget(actor)
    try:
        if platform:
            result, log = smoke_platform(actor, budget, actor_id, build)
        else:
            result, log = smoke_docker(actor, budget, image)
    except Exception as error:  # noqa: BLE001 - the report has to exist even when Docker dies
        detail = getattr(error, "stderr", None) or getattr(error, "stdout", None) or ""
        message = f"{type(error).__name__}: {error}"
        if detail and str(detail) not in message:
            message = f"{message}\n{detail}"
        print(message, file=sys.stderr)
        result = _empty_result(f"FAILED ({type(error).__name__})")
        log = message
        problems = [message]
    else:
        problems = evaluate(budget, result)
    if report:
        _write_report(report, actor, result, problems, log)
    print(f"\n{actor.name} fixture smoke ({'platform' if platform else 'docker'})")
    print(f"  status          {result['status']}")
    memory = result.get("memoryMaxMbytes")
    print(f"  peak memory     {'n/a' if memory is None else f'{memory:.0f} MB'} (budget {budget['memoryMbytes']} MB)")
    print(f"  duration        {result['durationSecs']:.0f}s (budget {budget['maxDurationSecs']}s)")
    print(f"  dataset rows    {result['itemCount']} (budget {budget['minItems']}-{budget['maxItems']})")
    print(f"  PPE charge      ${result['chargeUsd']} {result['chargedEvents']} (budget ${budget['maxChargeUsd']})")
    if result.get("usageUsd") is not None:
        print(f"  platform usage  ${result['usageUsd']:.4f}")
    if result.get("runUrl"):
        print(f"  run             {result['runUrl']}")
    if problems:
        print("\nOver budget:\n  " + "\n  ".join(problems))
        print("\nLast log lines:\n" + log)
        return 1
    print("  OK: inside budget")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("bundle", "check"):
        cmd = sub.add_parser(name)
        cmd.add_argument("actors", nargs="*", help="Actor folder names. Default: all")
    sub.add_parser("list", help="Print the Actor folder names as JSON")
    budgets = sub.add_parser("budgets", help="Print the budget table for README.md")
    budgets.add_argument("--write", action="store_true", help="Rewrite the README.md table")
    iso = sub.add_parser("isolate", help="Probe imports from a temp copy of the build context")
    iso.add_argument("actor")
    prb = sub.add_parser("probe", help="Import every module from the bundle (run inside the image)")
    prb.add_argument("--actor-dir", default=".")
    prb.add_argument("--repo", help="Repo checkout used to tell repo modules from third-party ones")
    prb.add_argument("--strict", action="store_true", help="Also fail on a missing third-party module")
    smk = sub.add_parser("smoke", help="Run fixtures/INPUT.json and enforce fixtures/budget.json")
    smk.add_argument("actor")
    smk.add_argument("--image", help="Use this built image instead of building one")
    smk.add_argument("--platform", action="store_true", help="Run the pushed Actor on Apify (APIFY_TOKEN)")
    smk.add_argument("--actor-id", help="Platform Actor id. Default: <me>/<actor.json name>")
    smk.add_argument("--build", help="Platform build tag or number. Default: the Actor default")
    smk.add_argument("--report", help="Write the result as JSON to this path")
    args = parser.parse_args(argv)

    if args.command == "bundle":
        for actor in actor_dirs(args.actors):
            print(f"{actor.name}: wrote {bundle(actor)} files to {BUNDLE_DIR}/")
        return 0
    if args.command == "check":
        return check(actor_dirs(args.actors))
    if args.command == "list":
        print(json.dumps([actor.name for actor in actor_dirs() if not actor.name.startswith("_")]))
        return 0
    if args.command == "budgets":
        if args.write:
            write_readme_table()
        print(budget_table())
        return 0
    if args.command == "isolate":
        return isolate(actor_dirs([args.actor])[0])
    if args.command == "probe":
        return probe(args.actor_dir, args.repo, args.strict)
    return smoke(
        actor_dirs([args.actor])[0],
        image=args.image,
        platform=args.platform,
        actor_id=args.actor_id,
        build=args.build,
        report=args.report,
    )


if __name__ == "__main__":
    sys.exit(main())
