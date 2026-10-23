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


SUCCESS = "success"
REJECTED = "rejected"
FAILED = "failed"
CANCELLED = "cancelled"

# A rejection means the manager refused the request as designed. CI reports it
# in run.json and the job summary but ends the workflow run successfully.
REJECTED_KINDS = frozenset({"usage", "bad_args", "unknown_script", "confirmation_required", "would_prompt"})


def failure_kind_for(exit_code, *, child_finished):
    """Return the summary failure_kind for a manager or child exit."""
    if child_finished:
        if exit_code == 0:
            return None
        return "child_exit"
    return FAILURE_KIND.get(exit_code)


def looks_like_usage_error(exit_code, stderr_tail: str | None) -> bool:
    """argparse and click exit 2 after printing a usage line."""
    return exit_code == USAGE and "usage:" in (stderr_tail or "").lower()


def outcome_for(exit_code, failure_kind, *, rejected: bool = False) -> str:
    """success, rejected, failed, or cancelled for a run summary."""
    if failure_kind == CANCELLED:
        return CANCELLED
    if exit_code == 0 and not failure_kind:
        return SUCCESS
    if rejected or failure_kind in REJECTED_KINDS:
        return REJECTED
    return FAILED


def summary_outcome(summary: dict) -> str:
    value = summary.get("outcome")
    if value in {SUCCESS, REJECTED, FAILED, CANCELLED}:
        return value
    return outcome_for(summary.get("exit_code"), summary.get("failure_kind"))
