"""Process exit codes for the script manager.

A child process can exit with one of these same numbers. Run summaries set
``failure_kind`` so a manager failure is not confused with a child exit.
"""

USAGE = 2
UNKNOWN_SCRIPT = 64
REGISTRY_INVALID = 65
MISSING_ENV = 66
NOT_RUNNABLE = 67
CONFIRMATION_REQUIRED = 68
WOULD_PROMPT = 69
TIMEOUT = 124
INTERRUPTED = 130

FAILURE_KIND = {
    UNKNOWN_SCRIPT: "unknown_script",
    REGISTRY_INVALID: "registry_invalid",
    MISSING_ENV: "missing_env",
    NOT_RUNNABLE: "not_runnable",
    CONFIRMATION_REQUIRED: "confirmation_required",
    WOULD_PROMPT: "would_prompt",
    TIMEOUT: "timeout",
    INTERRUPTED: "interrupted",
}

# The manager refused the run on purpose. CI records these in run.json and
# finishes the workflow successfully so GitHub does not mail a failure.
EXPECTED_REJECTION_KINDS = frozenset({"usage", "unknown_script", "confirmation_required"})
EXPECTED_REJECTION_CODES = frozenset({USAGE, UNKNOWN_SCRIPT, CONFIRMATION_REQUIRED})


def failure_kind_for(exit_code, *, child_finished):
    """Return the summary failure_kind for a manager or child exit."""
    if child_finished:
        if exit_code == 0:
            return None
        return "child_exit"
    return FAILURE_KIND.get(exit_code)


def is_expected_rejection(exit_code, failure_kind) -> bool:
    """True when the manager refused the run and the script did not fail."""
    if failure_kind == "child_exit":
        return False
    if failure_kind in EXPECTED_REJECTION_KINDS:
        return True
    return failure_kind in (None, "") and exit_code in EXPECTED_REJECTION_CODES


def result_label(summary: dict) -> str:
    """Short status for the job summary: ok, rejected, cancelled, or failed."""
    kind = summary.get("failure_kind")
    if kind == "cancelled":
        return "cancelled"
    code = summary.get("exit_code")
    if is_expected_rejection(code if isinstance(code, int) else -1, kind):
        return "rejected"
    if not kind and code in (0, None):
        return "ok"
    return "failed"
