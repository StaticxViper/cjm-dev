"""Load and schema-check the script registry.

The schema is enforced by this module, not by the jsonschema package. The
sibling ``registry.schema.json`` documents the same rules for people editing
the file. JSON is used because the repo's other configs are JSON and the
manager stays on the standard library plus python-dotenv.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_STATUSES = {"active", "broken", "legacy", "planned"}
_SIDE_EFFECTS = {
    "external_api",
    "external_post",
    "sends_messages",
    "spends_money",
    "writes_repo_files",
    "host_changes",
}
_SCRIPT_KEYS = {
    "name",
    "description",
    "status",
    "status_reason",
    "entry",
    "cwd",
    "pythonpath",
    "alias_of",
    "default_args",
    "non_interactive_args",
    "interactive",
    "help_supported",
    "env",
    "deps",
    "needs_playwright",
    "playwright_when_args_any",
    "timeout_seconds",
    "outputs",
    "side_effects",
    "confirm_required",
    "ci_allowed",
    "local_only",
    "stateful_files",
    "tags",
    "schedule",
    "docs",
    "issue",
    "menu",
    "prompts",
}
_ENTRY_KEYS = {"type", "path", "module"}
_ENV_KEYS = {"required", "optional", "conditional"}
_COND_KEYS = {"when_args_any", "require"}
_DEPS_KEYS = {"requirements", "extras", "system"}
_SCHEDULE_KEYS = {"cron", "tz", "note"}
_MENU_KINDS = {"leadgen", "opp-finder", "clip-generator", "montage-builder", "flags", "confirm"}
_PROMPT_KINDS = {"str", "int", "float", "bool", "choice"}
_PROMPT_KEYS = {"arg", "prompt", "kind", "optional", "choices", "split"}
# Main entry points. validate checks these only against the packaged registry.
MENU_REQUIRED = {
    "leadgen": "leadgen",
    "leadenrich": "flags",
    "leadenrich-playwright": "flags",
    "stock-analyzer": "confirm",
    "property-listing-gen": "flags",
    "clip-generator": "clip-generator",
    "montage-builder": "montage-builder",
    "source-recruiters": "confirm",
    "draft-emails": "confirm",
    "city-data": "flags",
    "grocery": "flags",
    "grocery-cli": "flags",
    "opp-finder-v2": "opp-finder",
}


class RegistryError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


@dataclass
class Script:
    name: str
    description: str
    status: str
    status_reason: str = ""
    entry_type: str = ""
    entry_path: str | None = None
    entry_module: str | None = None
    cwd: str = "."
    pythonpath: list[str] = field(default_factory=list)
    alias_of: str | None = None
    default_args: list[str] = field(default_factory=list)
    non_interactive_args: list[str] = field(default_factory=list)
    interactive: bool = False
    help_supported: bool = False
    env_required: list[str] = field(default_factory=list)
    env_optional: list[str] = field(default_factory=list)
    env_conditional: list[dict] = field(default_factory=list)
    deps_requirements: str = "requirements/requirements.txt"
    deps_extras: list[str] = field(default_factory=list)
    deps_system: list[str] = field(default_factory=list)
    needs_playwright: bool | str = False
    playwright_when_args_any: list[str] = field(default_factory=list)
    timeout_seconds: int = 3600
    outputs: list[str] = field(default_factory=list)
    side_effects: list[str] = field(default_factory=list)
    confirm_required: bool = False
    ci_allowed: bool = False
    local_only: bool = False
    stateful_files: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    schedule: dict | None = None
    docs: str | None = None
    issue: str | None = None
    menu: str | None = None
    prompts: list[dict] = field(default_factory=list)

    def copy(self) -> Script:
        return Script(
            name=self.name,
            description=self.description,
            status=self.status,
            status_reason=self.status_reason,
            entry_type=self.entry_type,
            entry_path=self.entry_path,
            entry_module=self.entry_module,
            cwd=self.cwd,
            pythonpath=list(self.pythonpath),
            alias_of=self.alias_of,
            default_args=list(self.default_args),
            non_interactive_args=list(self.non_interactive_args),
            interactive=self.interactive,
            help_supported=self.help_supported,
            env_required=list(self.env_required),
            env_optional=list(self.env_optional),
            env_conditional=[dict(item) for item in self.env_conditional],
            deps_requirements=self.deps_requirements,
            deps_extras=list(self.deps_extras),
            deps_system=list(self.deps_system),
            needs_playwright=self.needs_playwright,
            playwright_when_args_any=list(self.playwright_when_args_any),
            timeout_seconds=self.timeout_seconds,
            outputs=list(self.outputs),
            side_effects=list(self.side_effects),
            confirm_required=self.confirm_required,
            ci_allowed=self.ci_allowed,
            local_only=self.local_only,
            stateful_files=list(self.stateful_files),
            tags=list(self.tags),
            schedule=dict(self.schedule) if self.schedule else None,
            docs=self.docs,
            issue=self.issue,
            menu=self.menu,
            prompts=[dict(item) for item in self.prompts],
        )

    def entry_dict(self) -> dict:
        if self.entry_type == "module":
            return {"type": "module", "module": self.entry_module}
        return {"type": "path", "path": self.entry_path}

    def declared_env_names(self) -> list[str]:
        names: list[str] = []
        for bucket in (self.env_required, self.env_optional):
            for name in bucket:
                if name not in names:
                    names.append(name)
        for rule in self.env_conditional:
            for name in rule.get("require", []):
                if name not in names:
                    names.append(name)
        return names


@dataclass
class Registry:
    version: int
    ignore_paths: list[str]
    scripts: dict[str, Script]
    path: Path | None = None

    def get(self, name: str) -> Script | None:
        return self.scripts.get(name)

    def ordered(self) -> list[Script]:
        return [self.scripts[name] for name in sorted(self.scripts)]


def bundled_registry_path() -> Path:
    return Path(__file__).resolve().parent / "registry.json"


def load_registry(path: Path | str) -> Registry:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RegistryError([f"cannot read registry {path}: {exc}"]) from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RegistryError([f"{path}: invalid JSON ({exc})"]) from exc
    return parse_registry(data, source=str(path), path=path)


def parse_registry(data, *, source: str = "registry", path: Path | None = None) -> Registry:
    errors: list[str] = []
    if not isinstance(data, dict):
        raise RegistryError([f"{source}: registry must be a JSON object"])
    _unknown(data, {"version", "ignore_paths", "scripts"}, f"{source}", errors)
    version = data.get("version")
    if version != 1:
        errors.append(f"{source}: version must be 1")
    ignore_paths = data.get("ignore_paths", [])
    if not isinstance(ignore_paths, list) or not all(isinstance(item, str) for item in ignore_paths):
        errors.append(f"{source}: ignore_paths must be a list of strings")
        ignore_paths = []
    raw_scripts = data.get("scripts")
    if not isinstance(raw_scripts, list):
        errors.append(f"{source}: scripts must be a list")
        raise RegistryError(errors)
    parsed: list[tuple[dict, Script]] = []
    names: list[str] = []
    for index, raw in enumerate(raw_scripts):
        label = f"{source} scripts[{index}]"
        if not isinstance(raw, dict):
            errors.append(f"{label}: must be an object")
            continue
        script, script_errors = _parse_script(raw, label)
        errors.extend(script_errors)
        if script is None:
            continue
        if script.name in names:
            errors.append(f"{label}: duplicate name {script.name!r}")
        names.append(script.name)
        parsed.append((raw, script))
    by_raw = {script.name: raw for raw, script in parsed}
    by_script = {script.name: script for _, script in parsed}
    resolved: dict[str, Script] = {}
    for name in by_script:
        _resolve_alias(name, by_raw, by_script, resolved, [], errors, source)
    if errors:
        raise RegistryError(errors)
    return Registry(version=1, ignore_paths=list(ignore_paths), scripts=resolved, path=path)


def entry_file(repo: Path, script: Script) -> Path | None:
    """Return the file that ``python`` will execute for this script, if it exists."""
    if script.entry_type == "path":
        if not script.entry_path:
            return None
        path = (repo / script.entry_path).resolve()
        return path if path.is_file() else None
    if script.entry_type != "module" or not script.entry_module:
        return None
    rel = Path(*script.entry_module.split("."))
    bases = []
    if script.cwd:
        bases.append(repo / script.cwd)
    bases.append(repo)
    for base in bases:
        module_py = (base / rel).with_suffix(".py")
        package_main = base / rel / "__main__.py"
        if module_py.is_file():
            return module_py.resolve()
        if package_main.is_file():
            return package_main.resolve()
    return None


def registered_files(repo: Path, registry: Registry) -> set[Path]:
    files = set()
    for script in registry.scripts.values():
        path = entry_file(repo, script)
        if path is not None:
            files.add(path)
        elif script.entry_type == "path" and script.entry_path:
            files.add((repo / script.entry_path).resolve())
    return files


def _resolve_alias(name, by_raw, by_script, resolved, stack, errors, source):
    if name in resolved:
        return resolved[name]
    if name not in by_script:
        errors.append(f"{source}: alias target {name!r} does not exist")
        return None
    if name in stack:
        errors.append(f"{source}: alias cycle involving {name!r}")
        return None
    raw = by_raw[name]
    base = by_script[name]
    alias_of = raw.get("alias_of")
    if not alias_of:
        resolved[name] = base
        return base
    target = _resolve_alias(alias_of, by_raw, by_script, resolved, stack + [name], errors, source)
    if target is None:
        return None
    script = target.copy()
    script.name = base.name
    script.description = base.description
    script.status = base.status
    script.status_reason = base.status_reason
    script.alias_of = alias_of
    script.issue = base.issue or script.issue
    script.docs = base.docs or script.docs
    script.default_args = list(base.default_args) + list(target.default_args)
    if "cwd" in raw:
        script.cwd = base.cwd
    if "entry" in raw:
        script.entry_type = base.entry_type
        script.entry_path = base.entry_path
        script.entry_module = base.entry_module
    if "pythonpath" in raw:
        script.pythonpath = list(base.pythonpath)
    if "non_interactive_args" in raw:
        script.non_interactive_args = list(base.non_interactive_args)
    if "interactive" in raw:
        script.interactive = base.interactive
    if "help_supported" in raw:
        script.help_supported = base.help_supported
    if "env" in raw:
        script.env_required = list(base.env_required)
        script.env_optional = list(base.env_optional)
        script.env_conditional = [dict(item) for item in base.env_conditional]
    if "deps" in raw:
        script.deps_requirements = base.deps_requirements
        script.deps_extras = list(base.deps_extras)
        script.deps_system = list(base.deps_system)
    if "needs_playwright" in raw:
        script.needs_playwright = base.needs_playwright
    if "playwright_when_args_any" in raw:
        script.playwright_when_args_any = list(base.playwright_when_args_any)
    if "timeout_seconds" in raw:
        script.timeout_seconds = base.timeout_seconds
    if "outputs" in raw:
        script.outputs = list(base.outputs)
    if "side_effects" in raw:
        script.side_effects = list(base.side_effects)
    if "confirm_required" in raw:
        script.confirm_required = base.confirm_required
    if "ci_allowed" in raw:
        script.ci_allowed = base.ci_allowed
    if "local_only" in raw:
        script.local_only = base.local_only
    if "stateful_files" in raw:
        script.stateful_files = list(base.stateful_files)
    if "tags" in raw:
        script.tags = list(base.tags)
    if "schedule" in raw:
        script.schedule = dict(base.schedule) if base.schedule else None
    # Menus are per entry point. An alias does not inherit the target's menu.
    script.menu = base.menu if "menu" in raw else None
    script.prompts = [dict(item) for item in base.prompts] if "prompts" in raw else []
    if script.needs_playwright == "conditional" and not script.playwright_when_args_any:
        errors.append(
            f"{source}: {name}: playwright_when_args_any is required when needs_playwright is conditional"
        )
    resolved[name] = script
    return script


def _parse_script(raw: dict, label: str) -> tuple[Script | None, list[str]]:
    errors: list[str] = []
    _unknown(raw, _SCRIPT_KEYS, label, errors)
    name = raw.get("name")
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
        errors.append(f"{label}: name must match {_NAME_RE.pattern}")
        name = name if isinstance(name, str) else f"<index {label}>"
    description = raw.get("description")
    if not isinstance(description, str) or not description.strip():
        errors.append(f"{label}: description must be a non-empty string")
        description = description if isinstance(description, str) else ""
    status = raw.get("status")
    if status not in _STATUSES:
        errors.append(f"{label}: status must be one of {sorted(_STATUSES)}")
        status = "active"
    status_reason = raw.get("status_reason", "")
    if status != "active":
        if not isinstance(status_reason, str) or not status_reason.strip():
            errors.append(f"{label}: status_reason is required when status is {status}")
            status_reason = ""
    elif status_reason not in ("", None) and not isinstance(status_reason, str):
        errors.append(f"{label}: status_reason must be a string")
        status_reason = ""
    alias_of = raw.get("alias_of")
    if alias_of is not None and not isinstance(alias_of, str):
        errors.append(f"{label}: alias_of must be a string")
        alias_of = None
    entry_type = ""
    entry_path = None
    entry_module = None
    if "entry" in raw:
        entry_type, entry_path, entry_module, entry_errors = _parse_entry(raw.get("entry"), label)
        errors.extend(entry_errors)
    elif not alias_of:
        errors.append(f"{label}: entry is required")
    cwd = raw.get("cwd", "." if alias_of else None)
    if not alias_of and not isinstance(cwd, str):
        errors.append(f"{label}: cwd is required and must be a repo-relative string")
        cwd = "."
    elif cwd is None:
        cwd = "."
    elif not isinstance(cwd, str) or not cwd.strip():
        errors.append(f"{label}: cwd must be a non-empty string")
        cwd = "."
    needs = raw.get("needs_playwright", None if alias_of else False)
    if "needs_playwright" in raw or not alias_of:
        if needs not in (True, False, "conditional"):
            errors.append(f"{label}: needs_playwright must be true, false, or \"conditional\"")
            needs = False
    when = _string_list(raw, "playwright_when_args_any", label, errors) or []
    if needs == "conditional" and "playwright_when_args_any" in raw and not when and not alias_of:
        errors.append(f"{label}: playwright_when_args_any is required when needs_playwright is conditional")
    if needs == "conditional" and not alias_of and not when:
        errors.append(f"{label}: playwright_when_args_any is required when needs_playwright is conditional")
    env_required, env_optional, env_conditional = _parse_env(raw.get("env", {}), label, errors)
    deps_requirements, deps_extras, deps_system = _parse_deps(raw.get("deps", {}), label, errors)
    timeout = raw.get("timeout_seconds", 3600)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
        errors.append(f"{label}: timeout_seconds must be a positive integer")
        timeout = 3600
    schedule = _parse_schedule(raw.get("schedule"), label, errors)
    docs = raw.get("docs")
    if docs is not None and not isinstance(docs, str):
        errors.append(f"{label}: docs must be a string")
        docs = None
    issue = raw.get("issue")
    if issue is not None and not isinstance(issue, str):
        errors.append(f"{label}: issue must be a string")
        issue = None
    menu = raw.get("menu")
    if "menu" in raw and menu not in _MENU_KINDS:
        errors.append(f"{label}: menu must be one of {sorted(_MENU_KINDS)}")
        menu = None
    prompts = _parse_prompts(raw, label, errors)
    if any(err.startswith(f"{label}: name must") for err in errors):
        return None, errors
    script = Script(
        name=name,
        description=description,
        status=status,
        status_reason=status_reason or "",
        entry_type=entry_type,
        entry_path=entry_path,
        entry_module=entry_module,
        cwd=cwd,
        pythonpath=_string_list(raw, "pythonpath", label, errors) or [],
        alias_of=alias_of,
        default_args=_string_list(raw, "default_args", label, errors) or [],
        non_interactive_args=_string_list(raw, "non_interactive_args", label, errors) or [],
        interactive=_bool_field(raw, "interactive", label, errors, default=False),
        help_supported=_bool_field(raw, "help_supported", label, errors, default=False),
        env_required=env_required,
        env_optional=env_optional,
        env_conditional=env_conditional,
        deps_requirements=deps_requirements,
        deps_extras=deps_extras,
        deps_system=deps_system,
        needs_playwright=needs if needs is not None else False,
        playwright_when_args_any=when,
        timeout_seconds=timeout,
        outputs=_string_list(raw, "outputs", label, errors) or [],
        side_effects=_side_effects(raw, label, errors),
        confirm_required=_bool_field(raw, "confirm_required", label, errors, default=False),
        ci_allowed=_bool_field(raw, "ci_allowed", label, errors, default=False),
        local_only=_bool_field(raw, "local_only", label, errors, default=False),
        stateful_files=_string_list(raw, "stateful_files", label, errors) or [],
        tags=_string_list(raw, "tags", label, errors) or [],
        schedule=schedule,
        docs=docs,
        issue=issue,
        menu=menu if isinstance(menu, str) else None,
        prompts=prompts,
    )
    return script, errors


def _parse_entry(entry, label):
    errors = []
    if not isinstance(entry, dict):
        return "", None, None, [f"{label}: entry must be an object"]
    _unknown(entry, _ENTRY_KEYS, f"{label}.entry", errors)
    entry_type = entry.get("type")
    if entry_type == "path":
        path = entry.get("path")
        if not isinstance(path, str) or not path.strip():
            errors.append(f"{label}: entry.path must be a non-empty string")
            path = None
        if "module" in entry:
            errors.append(f"{label}: path entries cannot set entry.module")
        return "path", path, None, errors
    if entry_type == "module":
        module = entry.get("module")
        if not isinstance(module, str) or not module.strip():
            errors.append(f"{label}: entry.module must be a non-empty string")
            module = None
        if "path" in entry:
            errors.append(f"{label}: module entries cannot set entry.path")
        return "module", None, module, errors
    errors.append(f"{label}: entry.type must be 'path' or 'module'")
    return "", None, None, errors


def _parse_env(env, label, errors):
    if env is None:
        return [], [], []
    if not isinstance(env, dict):
        errors.append(f"{label}: env must be an object")
        return [], [], []
    _unknown(env, _ENV_KEYS, f"{label}.env", errors)
    required = _string_list(env, "required", f"{label}.env", errors) or []
    optional = _string_list(env, "optional", f"{label}.env", errors) or []
    conditional = []
    raw_rules = env.get("conditional", [])
    if raw_rules is None:
        raw_rules = []
    if not isinstance(raw_rules, list):
        errors.append(f"{label}.env: conditional must be a list")
        return required, optional, []
    for index, rule in enumerate(raw_rules):
        rule_label = f"{label}.env.conditional[{index}]"
        if not isinstance(rule, dict):
            errors.append(f"{rule_label}: must be an object")
            continue
        _unknown(rule, _COND_KEYS, rule_label, errors)
        when = _string_list(rule, "when_args_any", rule_label, errors) or []
        require = _string_list(rule, "require", rule_label, errors) or []
        if not when or not require:
            errors.append(f"{rule_label}: when_args_any and require must be non-empty")
        conditional.append({"when_args_any": when, "require": require})
    return required, optional, conditional


def _parse_deps(deps, label, errors):
    if not deps:
        return "requirements/requirements.txt", [], []
    if not isinstance(deps, dict):
        errors.append(f"{label}: deps must be an object")
        return "requirements/requirements.txt", [], []
    _unknown(deps, _DEPS_KEYS, f"{label}.deps", errors)
    requirements = deps.get("requirements", "requirements/requirements.txt")
    if not isinstance(requirements, str) or not requirements.strip():
        errors.append(f"{label}: deps.requirements must be a string")
        requirements = "requirements/requirements.txt"
    extras = _string_list(deps, "extras", f"{label}.deps", errors) or []
    system = _string_list(deps, "system", f"{label}.deps", errors) or []
    return requirements, extras, system


def _parse_prompts(raw, label, errors):
    if "prompts" not in raw:
        return []
    value = raw.get("prompts")
    if not isinstance(value, list):
        errors.append(f"{label}: prompts must be a list")
        return []
    prompts = []
    for index, item in enumerate(value):
        item_label = f"{label}.prompts[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{item_label}: must be an object")
            continue
        _unknown(item, _PROMPT_KEYS, item_label, errors)
        arg = item.get("arg")
        prompt = item.get("prompt")
        kind = item.get("kind", "str")
        if not isinstance(arg, str) or not arg.strip():
            errors.append(f"{item_label}: arg must be a non-empty string")
            arg = ""
        if not isinstance(prompt, str) or not prompt.strip():
            errors.append(f"{item_label}: prompt must be a non-empty string")
            prompt = arg or "value"
        if kind not in _PROMPT_KINDS:
            errors.append(f"{item_label}: kind must be one of {sorted(_PROMPT_KINDS)}")
            kind = "str"
        choices = item.get("choices", [])
        if "choices" in item and (
            not isinstance(choices, list) or not all(isinstance(choice, str) for choice in choices)
        ):
            errors.append(f"{item_label}: choices must be a list of strings")
            choices = []
        if kind == "choice" and not choices:
            errors.append(f"{item_label}: choice prompts need a non-empty choices list")
        split = item.get("split", False)
        if not isinstance(split, bool):
            errors.append(f"{item_label}: split must be a boolean")
            split = False
        optional = item.get("optional", True)
        if not isinstance(optional, bool):
            errors.append(f"{item_label}: optional must be a boolean")
            optional = True
        prompts.append(
            {
                "arg": arg,
                "prompt": prompt,
                "kind": kind,
                "optional": optional,
                "choices": list(choices or []),
                "split": bool(split),
            }
        )
    return prompts


def _parse_schedule(schedule, label, errors):
    if schedule is None:
        return None
    if not isinstance(schedule, dict):
        errors.append(f"{label}: schedule must be an object")
        return None
    _unknown(schedule, _SCHEDULE_KEYS, f"{label}.schedule", errors)
    cron = schedule.get("cron")
    if not isinstance(cron, str) or not cron.strip():
        errors.append(f"{label}: schedule.cron must be a string")
        cron = ""
    parsed = {"cron": cron}
    for key in ("tz", "note"):
        if key in schedule:
            if not isinstance(schedule[key], str):
                errors.append(f"{label}: schedule.{key} must be a string")
            else:
                parsed[key] = schedule[key]
    return parsed


def _side_effects(raw, label, errors):
    values = _string_list(raw, "side_effects", label, errors) or []
    for value in values:
        if value not in _SIDE_EFFECTS:
            errors.append(f"{label}: unknown side effect {value!r}")
    return values


def _string_list(raw, key, label, errors):
    if key not in raw:
        return None
    value = raw[key]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        errors.append(f"{label}: {key} must be a list of strings")
        return []
    return list(value)


def _bool_field(raw, key, label, errors, *, default):
    if key not in raw:
        return default
    value = raw[key]
    if not isinstance(value, bool):
        errors.append(f"{label}: {key} must be a boolean")
        return default
    return value


def _unknown(raw, allowed, label, errors):
    if not isinstance(raw, dict):
        return
    extra = sorted(set(raw) - allowed)
    for key in extra:
        errors.append(f"{label}: unknown field {key!r}")
