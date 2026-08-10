"""Linux `/proc/<tid>/stat` process-state check.

Used to filter samples to threads that are actually running (not
blocked/idle) at sample time: read the thread's process state character from
`/proc`, rather than computing a CPU-time delta.
"""

from pathlib import Path

_RUNNING_STATE = "R"


def parse_state(raw: str) -> str | None:
    """Parse the state char out of `raw` `/proc/<tid>/stat` content.

    Returns None if `raw` is malformed (e.g. truncated). The `comm` (thread
    name) field is parenthesized and can itself contain spaces or nested
    parens, so the state char must be found relative to the *last* `)` in the
    line, not by naively splitting on whitespace.
    """
    try:
        return raw[raw.rindex(")") + 1 :].split(None, 1)[0]
    except (ValueError, IndexError):
        return None


def is_running(native_id: int) -> bool | None:
    """Return whether the Linux thread `native_id` is in the running ('R') state.

    Reads /proc/<native_id>/stat. Returns None if the state can't be
    determined (thread exited, permission error, malformed read) -- callers
    should treat None as "not confirmed running" for filtering purposes.
    """
    try:
        raw = Path(f"/proc/{native_id}/stat").read_text()
    except OSError:
        return None

    state = parse_state(raw)
    if state is None:
        return None
    return state == _RUNNING_STATE
