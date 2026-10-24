"""Build a child command and run it in its own process group."""

from __future__ import annotations

import glob
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from scripts.script_manager import exit_codes
from scripts.script_manager.envcheck import (
    EnvFileError,
    build_child_env,
    env_scope_mode,
    is_set,
    load_dotenv_file,
    merged_env,
    missing_names,
    playwright_needed,
    triggered_rules,
)
from scripts.script_manager.registry import Script, entry_file

logger = logging.getLogger("script_manager")

_PLAYWRIGHT_OK: tuple[bool, str] | None = None
_INSTALL_HINT = "python -m playwright install chromium"
_TAIL_BYTES = 8000
_DATA_BYTES = 1_000_000
_OUTPUT_FILE_BYTES = 200_000
_OUTPUT_TOTAL_BYTES = 1_000_000
_OUTPUT_FILE_COUNT = 20


@dataclass
class RunOptions:
    passthrough: list[str] = field(default_factory=list)
    dry_run: bool = False
    timeout: int | None = None
    env_file: Path | None = None
    no_dotenv: bool = False
    non_interactive: bool | None = None
    yes: bool = False
    force: bool = False
    no_defaults: bool = False
    summary_json: Path | None = None
    github_summary: bool = False
    ci: bool = False
    env_scope: str | None = None
    skip_env_check: bool = False
    skip_playwright: bool = False
    skip_system_deps: bool = False
    skip_confirm: bool = False
    process_env: dict[str, str] | None = None
    request_id: str | None = None
    trigger: dict | None = None
    run_url: str | None = None
    run_id: str | None = None


def decide_noninteractive(explicit_noninteractive: bool, explicit_interactive: bool, process: dict | None = None) -> bool:
    if explicit_interactive:
        return False
    if explicit_noninteractive:
        return True
    source = os.environ if process is None else process
    if str(source.get("CI", "")).strip().lower() in {"1", "true", "yes"}:
        return True
    try:
        return not sys.stdin.isatty()
    except Exception:
        return True


def command_args(script: Script, passthrough: list[str], *, no_defaults: bool, non_interactive: bool) -> list[str]:
    """Args after the interpreter and entry, including defaults when requested."""
    defaults = [] if no_defaults else list(script.default_args)
    extra = list(passthrough)
    if non_interactive and not extra and script.non_interactive_args:
        extra = list(script.non_interactive_args)
    return defaults + extra


def would_prompt(script: Script, passthrough: list[str], non_interactive: bool) -> bool:
    if not non_interactive or not script.interactive:
        return False
    if passthrough or script.non_interactive_args:
        return False
    return True


def build_argv(repo: Path, script: Script, args: list[str]) -> list[str]:
    if script.entry_type == "module":
        prefix = [sys.executable, "-m", script.entry_module or ""]
    else:
        path = (repo / (script.entry_path or "")).resolve()
        prefix = [sys.executable, str(path)]
    return prefix + list(args)


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def format_time(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def blank_summary(name: str, status: str | None, started: datetime) -> dict:
    finished = started
    return {
        "name": name,
        "status": status,
        "argv": [],
        "cwd": None,
        "started_at": format_time(started),
        "finished_at": format_time(finished),
        "duration_s": 0.0,
        "exit_code": None,
        "failure_kind": None,
        "env_missing": [],
        "outputs": [],
        "timed_out": False,
        "dry_run": False,
        "request_id": None,
        "trigger": None,
        "run_url": None,
        "run_id": None,
        "message": "",
        "data": None,
        "stdout_tail": "",
        "stderr_tail": "",
        "output_files": {},
    }


def finish_summary(summary: dict, started: datetime, exit_code: int, *, child_finished: bool, finished: datetime | None = None) -> dict:
    finished = finished or utc_now()
    summary["finished_at"] = format_time(finished)
    summary["duration_s"] = float((finished - started).total_seconds())
    summary["exit_code"] = exit_code
    summary["failure_kind"] = exit_codes.failure_kind_for(exit_code, child_finished=child_finished)
    return summary


def read_output_files(repo: Path, paths: list[str]) -> dict:
    """Text or JSON contents of declared output files, capped so a log tree cannot fill the summary."""
    found: dict = {}
    total = 0
    for rel in paths:
        if len(found) >= _OUTPUT_FILE_COUNT or total >= _OUTPUT_TOTAL_BYTES:
            break
        path = (repo / rel).resolve()
        try:
            path.relative_to(repo.resolve())
        except ValueError:
            continue
        if not path.is_file():
            continue
        size = path.stat().st_size
        if size > _OUTPUT_FILE_BYTES:
            found[rel] = {"omitted": True, "bytes": size}
            continue
        raw = path.read_bytes()
        if b"\0" in raw[:1024]:
            found[rel] = {"binary": True, "bytes": len(raw)}
            continue
        text = raw.decode("utf-8", errors="replace")
        total += len(text)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        found[rel] = parsed if isinstance(parsed, (dict, list)) else text
    return found


def expand_outputs(repo: Path, patterns: list[str]) -> list[str]:
    found: list[str] = []
    for pattern in patterns:
        matches = glob.glob(str(repo / pattern), recursive=True)
        for match in matches:
            path = Path(match)
            if path.is_file():
                found.append(path.resolve().relative_to(repo.resolve()).as_posix())
    return sorted(set(found))


def system_dep_status(names: list[str]) -> list[tuple[str, bool]]:
    return [(name, shutil.which(name) is not None) for name in names]


def playwright_status() -> tuple[bool, str]:
    """Return whether Playwright can launch its installed Chromium build."""
    global _PLAYWRIGHT_OK
    if _PLAYWRIGHT_OK is not None:
        return _PLAYWRIGHT_OK
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _PLAYWRIGHT_OK = (False, f"playwright is not installed. Run: {_INSTALL_HINT}")
        return _PLAYWRIGHT_OK
    try:
        with sync_playwright() as playwright:
            executable = Path(playwright.chromium.executable_path)
    except Exception as exc:
        _PLAYWRIGHT_OK = (False, f"Playwright Chromium is not available ({exc}). Run: {_INSTALL_HINT}")
        return _PLAYWRIGHT_OK
    if not executable.is_file():
        _PLAYWRIGHT_OK = (False, f"Playwright Chromium is not installed. Run: {_INSTALL_HINT}")
        return _PLAYWRIGHT_OK
    _PLAYWRIGHT_OK = (True, "")
    return _PLAYWRIGHT_OK


def _popen(argv: list[str], cwd: Path, env: dict[str, str], *, stdin, stdout=None, stderr=None):
    kwargs = {
        "cwd": str(cwd),
        "env": env,
        "stdin": stdin,
        "stdout": stdout,
        "stderr": stderr,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(argv, **kwargs)


def _signal_group(proc: subprocess.Popen, kill: bool) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        flags = ["/F"] if kill else []
        subprocess.run(
            ["taskkill", *flags, "/PID", str(proc.pid), "/T"],
            capture_output=True,
            check=False,
        )
        return
    sig = signal.SIGKILL if kill else signal.SIGTERM
    try:
        os.killpg(proc.pid, sig)
    except OSError:
        if kill:
            proc.kill()
        else:
            proc.terminate()


class _StreamCapture:
    """Keep a bounded copy of a child stream for the run summary, and forward it live."""

    def __init__(self) -> None:
        self._data = bytearray()
        self._tail = bytearray()
        self.truncated = False
        self._lock = threading.Lock()

    def add(self, chunk: bytes) -> None:
        with self._lock:
            if len(self._data) < _DATA_BYTES:
                room = _DATA_BYTES - len(self._data)
                self._data.extend(chunk[:room])
                if len(chunk) > room:
                    self.truncated = True
            else:
                self.truncated = True
            self._tail.extend(chunk)
            if len(self._tail) > _TAIL_BYTES:
                del self._tail[: len(self._tail) - _TAIL_BYTES]

    def tail_text(self) -> str:
        with self._lock:
            return self._tail.decode("utf-8", errors="replace")

    def json_data(self):
        """Parse stdout when the whole captured stream is one JSON object or array."""
        with self._lock:
            if self.truncated:
                return None
            text = self._data.decode("utf-8", errors="replace").strip()
        if not text or text[0] not in "{[":
            return None
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return None
        if isinstance(value, (dict, list)):
            return value
        return None


def _forward_chunk(forward, chunk: bytes) -> None:
    try:
        buffer = getattr(forward, "buffer", None)
        if buffer is not None:
            buffer.write(chunk)
            buffer.flush()
            return
        forward.write(chunk.decode("utf-8", errors="replace"))
        forward.flush()
    except Exception:
        return


def _start_reader(stream, capture: _StreamCapture, forward) -> threading.Thread:
    def _read() -> None:
        try:
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    break
                capture.add(chunk)
                _forward_chunk(forward, chunk)
        finally:
            try:
                stream.close()
            except Exception:
                pass

    thread = threading.Thread(target=_read, daemon=True)
    thread.start()
    return thread


def _wait_with_timeout(proc: subprocess.Popen, timeout: int) -> tuple[int, bool, bool]:
    """Return (exit_code, timed_out, interrupted)."""
    try:
        code = proc.wait(timeout=timeout)
        return int(code), False, False
    except subprocess.TimeoutExpired:
        _signal_group(proc, kill=False)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _signal_group(proc, kill=True)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        return exit_codes.TIMEOUT, True, False
    except KeyboardInterrupt:
        _signal_group(proc, kill=False)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _signal_group(proc, kill=True)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        return exit_codes.INTERRUPTED, False, True


def status_refusal(script: Script, options: RunOptions) -> tuple[int, str] | None:
    """Refuse a script that is not active. ``--ci`` ignores ``--force``."""
    if script.status == "active":
        return None
    if options.ci:
        return (
            exit_codes.NOT_RUNNABLE,
            f"{script.name}: status is {script.status} ({script.status_reason or 'no reason recorded'}). Refusing --ci.",
        )
    if options.force:
        return None
    return (
        exit_codes.NOT_RUNNABLE,
        f"{script.name}: status is {script.status} ({script.status_reason or 'no reason recorded'}). Pass --force to run it anyway.",
    )


def entry_refusal(repo: Path, script: Script) -> tuple[int, str] | None:
    """Refuse a script whose entry or working directory is not in this checkout."""
    if script.status == "planned" and entry_file(repo, script) is None and script.entry_type == "path":
        missing = script.entry_path or script.entry_module
        return exit_codes.NOT_RUNNABLE, f"{script.name}: planned entry is not in this checkout ({missing})."
    if script.status == "planned" and script.entry_type == "module" and entry_file(repo, script) is None:
        return (
            exit_codes.NOT_RUNNABLE,
            f"{script.name}: planned module {script.entry_module} is not in this checkout.",
        )
    if script.entry_type == "path" and not (repo / (script.entry_path or "")).is_file():
        return exit_codes.NOT_RUNNABLE, f"{script.name}: entry file does not exist: {script.entry_path}"
    if script.entry_type == "module" and entry_file(repo, script) is None:
        return (
            exit_codes.NOT_RUNNABLE,
            f"{script.name}: module {script.entry_module} was not found from cwd {script.cwd}",
        )
    cwd = (repo / script.cwd).resolve()
    if not cwd.is_dir():
        return exit_codes.NOT_RUNNABLE, f"{script.name}: working directory does not exist: {script.cwd}"
    return None


def ci_access_refusal(script: Script, options: RunOptions) -> tuple[int, str] | None:
    """Refuse local-only scripts and scripts that are not allowed in CI."""
    if not options.ci:
        return None
    if script.local_only:
        return exit_codes.NOT_RUNNABLE, f"{script.name}: local_only is true. Refusing --ci."
    if not script.ci_allowed:
        return exit_codes.NOT_RUNNABLE, f"{script.name}: ci_allowed is false. Refusing --ci."
    return None


def confirm_refusal(script: Script, options: RunOptions) -> tuple[int, str] | None:
    """Side effects require confirm on CI runs. ``confirm_required`` always does, except dry runs."""
    if options.dry_run or options.yes or options.skip_confirm:
        return None
    reasons = []
    if script.confirm_required:
        reasons.append("confirm_required")
    if options.ci and script.side_effects:
        reasons.append("side_effects (" + ", ".join(script.side_effects) + ")")
    if not reasons:
        return None
    return (
        exit_codes.CONFIRMATION_REQUIRED,
        f"{script.name}: confirmation required ({'; '.join(reasons)}). Pass --yes or confirm=true.",
    )


def run_script(repo: Path, script: Script, options: RunOptions) -> dict:
    started = utc_now()
    summary = blank_summary(script.name, script.status, started)
    summary["dry_run"] = options.dry_run
    summary["request_id"] = options.request_id
    summary["trigger"] = options.trigger or {"event": "cli", "actor": None, "caller": None}
    summary["run_url"] = options.run_url
    summary["run_id"] = options.run_id
    if options.non_interactive is None:
        non_interactive = decide_noninteractive(False, False, options.process_env)
    else:
        non_interactive = options.non_interactive

    args = command_args(
        script,
        options.passthrough,
        no_defaults=options.no_defaults,
        non_interactive=non_interactive,
    )
    argv = build_argv(repo, script, args)
    cwd = (repo / script.cwd).resolve()
    summary["argv"] = argv
    summary["cwd"] = str(cwd)
    logger.info("command: %s", " ".join(_quote(part) for part in argv))
    logger.info("cwd: %s", cwd)

    def done(code: int, *, child_finished: bool = False, expand: bool = False, finished: datetime | None = None) -> dict:
        finish_summary(summary, started, code, child_finished=child_finished, finished=finished)
        if expand:
            summary["outputs"] = expand_outputs(repo, script.outputs)
            summary["output_files"] = read_output_files(repo, summary["outputs"])
        _emit_summary(summary, options)
        return summary

    for refusal in (status_refusal(script, options), entry_refusal(repo, script)):
        if refusal is not None:
            code, message = refusal
            summary["message"] = message
            logger.error("%s", message)
            return done(code)
    for refusal in (ci_access_refusal(script, options), confirm_refusal(script, options)):
        if refusal is not None:
            code, message = refusal
            summary["message"] = message
            logger.error("%s", message)
            return done(code)
    if would_prompt(script, options.passthrough, non_interactive):
        summary["message"] = (
            f"{script.name}: this script prompts on stdin. Pass script args after -- , or add non_interactive_args."
        )
        logger.error("%s", summary["message"])
        return done(exit_codes.WOULD_PROMPT)

    try:
        dotenv = load_dotenv_file(repo, options.env_file, options.no_dotenv)
    except EnvFileError as exc:
        logger.error("%s", exc)
        return done(exit_codes.USAGE)
    report_env = merged_env(options.process_env, dotenv)
    report = missing_names(script, args, report_env)
    summary["env_missing"] = report["required_missing"] + report["conditional_missing"]
    if summary["env_missing"] and not options.skip_env_check:
        summary["message"] = (
            f"{script.name}: missing required env: {', '.join(summary['env_missing'])} "
            "(set them in .env or the environment)."
        )
        logger.error("%s", summary["message"])
        return done(exit_codes.MISSING_ENV)
    if not options.skip_system_deps:
        missing_deps = [name for name, found in system_dep_status(script.deps_system) if not found]
        if missing_deps:
            summary["message"] = f"{script.name}: missing system dependency: {', '.join(missing_deps)}"
            logger.error("%s", summary["message"])
            return done(exit_codes.NOT_RUNNABLE)
    needs_browser = playwright_needed(script, args)
    if needs_browser and not options.skip_playwright:
        ok, detail = playwright_status()
        if not ok:
            summary["message"] = f"{script.name}: {detail}"
            logger.error("%s", summary["message"])
            return done(exit_codes.NOT_RUNNABLE)

    scope = env_scope_mode(options.env_scope, options.process_env)
    logger.info("env scope: %s", scope)
    if options.dry_run:
        for line in describe_env(script, args, report_env):
            logger.info("%s", line)
        logger.info("dry-run: not started")
        return done(0)

    child_env = build_child_env(
        repo,
        script,
        env_file=options.env_file,
        no_dotenv=options.no_dotenv,
        env_scope=options.env_scope,
        process=options.process_env,
    )
    stdin = subprocess.DEVNULL if non_interactive else None
    timeout = options.timeout if options.timeout is not None else script.timeout_seconds
    capture_output = non_interactive
    stdout_capture = _StreamCapture() if capture_output else None
    stderr_capture = _StreamCapture() if capture_output else None
    try:
        proc = _popen(
            argv,
            cwd,
            child_env,
            stdin=stdin,
            stdout=subprocess.PIPE if capture_output else None,
            stderr=subprocess.PIPE if capture_output else None,
        )
    except OSError as exc:
        logger.error("%s: failed to start: %s", script.name, exc)
        summary["message"] = f"{script.name}: failed to start: {exc}"
        return done(exit_codes.NOT_RUNNABLE)
    readers = []
    if capture_output:
        readers = [
            _start_reader(proc.stdout, stdout_capture, sys.stdout),
            _start_reader(proc.stderr, stderr_capture, sys.stderr),
        ]
    try:
        code, timed_out, interrupted = _wait_with_timeout(proc, timeout)
    finally:
        for thread in readers:
            thread.join(timeout=5)
    if stdout_capture is not None and stderr_capture is not None:
        summary["stdout_tail"] = stdout_capture.tail_text()
        summary["stderr_tail"] = stderr_capture.tail_text()
        summary["data"] = stdout_capture.json_data()
    summary["timed_out"] = timed_out
    if timed_out:
        logger.error("%s: timed out after %ss", script.name, timeout)
    if interrupted:
        logger.error("%s: interrupted", script.name)
    return done(
        code,
        child_finished=not timed_out and not interrupted,
        expand=True,
        finished=utc_now(),
    )


def smoke_import(repo: Path, script: Script, *, timeout: int = 30) -> tuple[int, str]:
    """Import a script without executing its ``__main__`` block.

    Broken scripts fail while importing the logger. Skipping ``__main__`` keeps
    a side-effect entry point (webhook POST, apt-get) from running if the
    import is later fixed.
    """
    path = entry_file(repo, script)
    if path is None and script.entry_type == "path" and script.entry_path:
        path = (repo / script.entry_path).resolve()
    if path is None:
        return exit_codes.NOT_RUNNABLE, f"{script.name}: entry is missing"
    code = (
        "import runpy, sys\n"
        f"sys.path.insert(0, {str(repo)!r})\n"
        f"runpy.run_path({str(path)!r}, run_name='script_manager_smoke')\n"
    )
    cwd = (repo / script.cwd).resolve()
    if not cwd.is_dir():
        cwd = repo
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONUNBUFFERED"] = "1"
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return exit_codes.TIMEOUT, f"{script.name}: import probe timed out"
    detail = (proc.stderr or proc.stdout or "").strip()
    return proc.returncode, detail


def _quote(part: str) -> str:
    if part == "" or any(char.isspace() for char in part):
        return '"' + part.replace('"', '\\"') + '"'
    return part


def _emit_summary(summary: dict, options: RunOptions) -> None:
    if options.summary_json is not None:
        path = Path(options.summary_json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_summary_json(summary), encoding="utf-8")
    if options.github_summary:
        _append_github_summary(summary)


def _summary_json(summary: dict) -> str:
    return json.dumps(summary, indent=2) + "\n"


def _append_github_summary(summary: dict) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        logger.info("GITHUB_STEP_SUMMARY is not set; skipping job summary")
        return
    missing = ", ".join(summary.get("env_missing") or []) or "none"
    failure = summary.get("failure_kind")
    trigger = summary.get("trigger") if isinstance(summary.get("trigger"), dict) else {}
    text = (
        f"### script-manager: {summary.get('name')} ({exit_codes.result_label(summary)})\n\n"
        f"- request_id: {summary.get('request_id')}\n"
        f"- trigger: {trigger.get('event')}\n"
        f"- caller: {trigger.get('caller')}\n"
        f"- run_url: {summary.get('run_url')}\n"
        f"- exit_code: {summary.get('exit_code')}\n"
        f"- failure_kind: {failure}\n"
        f"- duration_s: {summary.get('duration_s')}\n"
        f"- timed_out: {summary.get('timed_out')}\n"
        f"- env_missing: {missing}\n\n"
    )
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(text)


def describe_env(script: Script, args: list[str], env: dict[str, str]) -> list[str]:
    """Human lines of env name status. Values are never included."""
    lines = []
    report = missing_names(script, args, env)
    missing_required = set(report["required_missing"])
    missing_optional = set(report["optional_missing"])
    lines.append("env required:")
    if script.env_required:
        for name in script.env_required:
            state = "missing" if name in missing_required else "present"
            lines.append(f"  {name}: {state}")
    else:
        lines.append("  (none)")
    lines.append("env optional:")
    if script.env_optional:
        for name in script.env_optional:
            state = "missing" if name in missing_optional else "present"
            lines.append(f"  {name}: {state}")
    else:
        lines.append("  (none)")
    lines.append("env conditional (explicit args only; saved settings and script defaults are not inferred):")
    if not script.env_conditional:
        lines.append("  (none)")
    active = triggered_rules(script, args)
    active_ids = {id(rule) for rule in active}
    for rule in script.env_conditional:
        tokens = ", ".join(rule.get("when_args_any", []))
        if id(rule) not in active_ids:
            lines.append(f"  when {tokens}: not triggered")
            continue
        for name in rule.get("require", []):
            state = "present" if _present(env, name) else "missing"
            lines.append(f"  when {tokens}: {name}: {state}")
    return lines


def _present(env, name) -> bool:
    return is_set(env, name)
