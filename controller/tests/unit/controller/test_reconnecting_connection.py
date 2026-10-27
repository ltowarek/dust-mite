import http

import pytest
from websockets.datastructures import Headers
from websockets.exceptions import (
    ConnectionClosedError,
    InvalidHandshake,
    InvalidMessage,
    InvalidStatus,
    InvalidURI,
)
from websockets.http11 import Response

from controller.reconnecting_connection import (
    DeliberateClose,
    classify_close,
    is_retryable,
)


@pytest.mark.parametrize(
    ("code", "reason", "expected"),
    [
        pytest.param(1006, "", None, id="no-close-frame"),
        pytest.param(1001, "shutting down", None, id="going-away"),
        pytest.param(
            1013,
            "another driver is connected",
            DeliberateClose("another driver is connected"),
            id="try-again-later",
        ),
        pytest.param(
            1008,
            "unknown path: /",
            DeliberateClose("unknown path: /"),
            id="policy-violation",
        ),
        pytest.param(1000, "", DeliberateClose(""), id="normal-closure"),
        pytest.param(
            1011,
            "internal error",
            DeliberateClose("internal error"),
            id="internal-error",
        ),
    ],
)
def test_classifies_a_close(
    code: int, reason: str, expected: DeliberateClose | None
) -> None:
    assert classify_close(code, reason) == expected


def _status(status: http.HTTPStatus) -> InvalidStatus:
    return InvalidStatus(Response(status, status.phrase, Headers()))


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(_status(http.HTTPStatus.SERVICE_UNAVAILABLE), id="busy"),
        pytest.param(_status(http.HTTPStatus.NOT_FOUND), id="not-found"),
        pytest.param(_status(http.HTTPStatus.FORBIDDEN), id="forbidden"),
        pytest.param(
            InvalidMessage("did not receive a valid HTTP response"), id="garbled"
        ),
        pytest.param(
            InvalidHandshake("missing Upgrade header"), id="invalid-handshake"
        ),
        pytest.param(ConnectionRefusedError(), id="refused"),
        pytest.param(TimeoutError(), id="timed-out"),
        pytest.param(ConnectionClosedError(None, None), id="lost"),
    ],
)
def test_retries_after_an_error_that_can_pass(error: Exception) -> None:
    assert is_retryable(error) is True


def test_gives_up_on_an_invalid_uri() -> None:
    error = InvalidURI("car.invalid", "scheme isn't ws or wss")

    assert is_retryable(error) is False
