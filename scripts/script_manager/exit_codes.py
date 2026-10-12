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


def failure_kind_for(exit_code, *, child_finished):
    """Return the summary failure_kind for a manager or child exit."""
    if child_finished:
        if exit_code == 0:
            return None
        return "child_exit"
    return FAILURE_KIND.get(exit_code)
