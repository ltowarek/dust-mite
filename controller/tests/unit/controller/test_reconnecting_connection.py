import itertools

import pytest
from websockets.frames import Close

from controller.reconnecting_connection import (
    DeliberateClose,
    classify_close,
    retry_delays,
)


@pytest.mark.parametrize(
    ("close", "expected"),
    [
        pytest.param(None, None, id="no-close-frame"),
        pytest.param(Close(1001, "shutting down"), None, id="going-away"),
        pytest.param(
            Close(1013, "another driver is connected"),
            DeliberateClose("another driver is connected"),
            id="try-again-later",
        ),
        pytest.param(
            Close(1008, "unknown path: /"),
            DeliberateClose("unknown path: /"),
            id="policy-violation",
        ),
        pytest.param(Close(1000, ""), DeliberateClose(""), id="normal-closure"),
        pytest.param(
            Close(1011, "internal error"),
            DeliberateClose("internal error"),
            id="internal-error",
        ),
    ],
)
def test_classifies_a_close(
    close: Close | None, expected: DeliberateClose | None
) -> None:
    assert classify_close(close) == expected


@pytest.mark.parametrize("attempt", [0, 1, 100])
def test_waits_one_second_before_each_retry(attempt: int) -> None:
    one_second = 1.0

    assert next(itertools.islice(retry_delays(), attempt, None)) == one_second
