"""Cron schedules stored on registry scripts.

GitHub Actions cron is written into the schedule workflow by ``--write``.
``--check`` fails when that block drifts from the registry. ``--due`` reports
scripts whose cron matched within the grace window, because a scheduled run
can start late.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.script_manager.registry import Registry, Script

BEGIN = "# script-manager:schedules:begin"
END = "# script-manager:schedules:end"
GRACE_MINUTES = 90
SCHEDULE_WORKFLOW = ".github/workflows/script_manager_schedule.yml"


class ScheduleError(Exception):
    pass


def scheduled_scripts(registry: Registry) -> list[Script]:
    rows = []
    for script in registry.ordered():
        if not script.schedule or not script.schedule.get("cron"):
            continue
        if script.status != "active" or script.local_only or not script.ci_allowed:
            continue
        rows.append(script)
    return rows


def cron_lines(registry: Registry) -> list[str]:
    """Unique cron expressions, registry order, as workflow list items."""
    seen: list[str] = []
    for script in scheduled_scripts(registry):
        cron = script.schedule["cron"].strip()
        parse_cron(cron)
        if cron not in seen:
            seen.append(cron)
    if not seen:
        seen.append("0 0 1 1 *")
    return [f"    - cron: '{cron}'" for cron in seen]


def render_schedule_block(registry: Registry) -> str:
    body = "\n".join(cron_lines(registry))
    return f"    {BEGIN}\n{body}\n    {END}"


def replace_schedule_block(text: str, block: str) -> str:
    start = text.find(BEGIN)
    end = text.find(END)
    if start < 0 or end < 0 or end < start:
        raise ScheduleError(f"schedule workflow is missing {BEGIN} / {END}")
    start_line = text.rfind("\n", 0, start)
    start_line = 0 if start_line < 0 else start_line + 1
    end_line = text.find("\n", end)
    if end_line < 0:
        end_line = len(text)
    else:
        end_line += 1
    return text[:start_line] + block + "\n" + text[end_line:]


def schedule_block_matches(text: str, registry: Registry) -> bool:
    expected = render_schedule_block(registry)
    start = text.find(BEGIN)
    end = text.find(END)
    if start < 0 or end < 0:
        return False
    start_line = text.rfind("\n", 0, start)
    start_line = 0 if start_line < 0 else start_line + 1
    end_line = text.find("\n", end)
    if end_line < 0:
        actual = text[start_line:]
    else:
        actual = text[start_line:end_line]
    return _normalize(actual) == _normalize(expected)


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def due_matrix(
    registry: Registry,
    now: datetime | None = None,
    grace_minutes: int = GRACE_MINUTES,
    cron: str | None = None,
) -> dict:
    """Scripts to run.

    A GitHub ``schedule`` event passes the cron that fired. That match ignores
    the clock, because the runner often starts long after the minute GitHub
    promised. A manual run keeps the grace window.
    """
    chosen = (cron or "").strip()
    if chosen:
        parse_cron(chosen)
        matched = [
            script
            for script in scheduled_scripts(registry)
            if script.schedule["cron"].strip() == chosen
        ]
        return {"include": [_due_row(script) for script in matched]}
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc).replace(second=0, microsecond=0)
    include = []
    for script in scheduled_scripts(registry):
        expression = script.schedule["cron"].strip()
        if is_due(expression, moment, grace_minutes):
            include.append(_due_row(script))
    return {"include": include}


def _due_row(script: Script) -> dict:
    return {
        "script": script.name,
        "confirm": bool(script.schedule.get("confirm")),
        "outputs": "",
    }


def is_due(expression: str, now: datetime, grace_minutes: int = GRACE_MINUTES) -> bool:
    fields = parse_cron(expression)
    moment = now.astimezone(timezone.utc).replace(second=0, microsecond=0)
    for delta in range(grace_minutes + 1):
        if cron_matches(fields, moment - timedelta(minutes=delta)):
            return True
    return False


def parse_cron(expression: str) -> tuple[str, str, str, str, str]:
    parts = expression.split()
    if len(parts) != 5:
        raise ScheduleError(f"cron must have 5 fields: {expression!r}")
    ranges = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
    for part, (low, high) in zip(parts, ranges):
        _validate_field(part, low, high, expression)
    return parts[0], parts[1], parts[2], parts[3], parts[4]


def cron_matches(fields: tuple[str, str, str, str, str], moment: datetime) -> bool:
    minute, hour, dom, month, dow = fields
    if not _field_matches(minute, moment.minute, 0, 59):
        return False
    if not _field_matches(hour, moment.hour, 0, 23):
        return False
    if not _field_matches(month, moment.month, 1, 12):
        return False
    dom_ok = _field_matches(dom, moment.day, 1, 31)
    dow_ok = _dow_matches(dow, moment)
    if dom == "*" and dow == "*":
        return True
    if dom == "*":
        return dow_ok
    if dow == "*":
        return dom_ok
    return dom_ok or dow_ok


def _dow_matches(field: str, moment: datetime) -> bool:
    # datetime.weekday() is Monday=0. Cron Sunday is 0 or 7.
    cron_dow = (moment.weekday() + 1) % 7
    if _field_matches(field, cron_dow, 0, 7):
        return True
    if cron_dow == 0 and _field_matches(field, 7, 0, 7):
        return True
    return False


def _validate_field(field: str, low: int, high: int, expression: str) -> None:
    if field == "*":
        return
    for part in field.split(","):
        base, step = _split_step(part, expression)
        if base == "*":
            start, end = low, high
        elif "-" in base:
            left, right = base.split("-", 1)
            start, end = _int_in(left, low, high, expression), _int_in(right, low, high, expression)
            if start > end:
                raise ScheduleError(f"cron range is reversed in {expression!r}")
        else:
            start = end = _int_in(base, low, high, expression)
        if step < 1:
            raise ScheduleError(f"cron step must be positive in {expression!r}")
        _ = (start, end)


def _field_matches(field: str, value: int, low: int, high: int) -> bool:
    if field == "*":
        return low <= value <= high
    for part in field.split(","):
        base, step = _split_step(part, field)
        if base == "*":
            start, end = low, high
        elif "-" in base:
            left, right = base.split("-", 1)
            start, end = int(left), int(right)
        else:
            start = end = int(base)
        if value < start or value > end:
            continue
        if (value - start) % step == 0:
            return True
    return False


def _split_step(part: str, expression: str) -> tuple[str, int]:
    if "/" not in part:
        return part, 1
    base, raw = part.split("/", 1)
    if not raw.isdigit() or not base:
        raise ScheduleError(f"cron step is invalid in {expression!r}")
    return base, int(raw)


def _int_in(text: str, low: int, high: int, expression: str) -> int:
    if not text.isdigit():
        raise ScheduleError(f"cron field is not a number in {expression!r}")
    value = int(text)
    if value < low or value > high:
        raise ScheduleError(f"cron value {value} is outside {low}-{high} in {expression!r}")
    return value
