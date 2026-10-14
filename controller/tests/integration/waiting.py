"""Polling for conditions that other threads make true."""

import time
from collections.abc import Callable

WAIT_TIMEOUT_S = 10
_POLL_INTERVAL_S = 0.05


def wait_for(condition: Callable[[], bool]) -> bool:
    """Return whether `condition` became true within `WAIT_TIMEOUT_S`."""
    deadline = time.monotonic() + WAIT_TIMEOUT_S
    while not condition():
        if time.monotonic() > deadline:
            return False
        time.sleep(_POLL_INTERVAL_S)
    return True
