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
from websockets.frames import CloseCode
from websockets.http11 import Response

from controller.reconnecting_connection import deliberate_close_reason, is_retryable


@pytest.mark.parametrize(
    ("code", "reason", "expected"),
    [
        pytest.param(None, None, None, id="no-close-frame"),
        pytest.param(CloseCode.ABNORMAL_CLOSURE, "", None, id="abnormal-closure"),
        pytest.param(CloseCode.GOING_AWAY, "shutting down", None, id="going-away"),
        pytest.param(
            CloseCode.TRY_AGAIN_LATER,
            "another driver is connected",
            "another driver is connected",
            id="try-again-later",
        ),
        pytest.param(
            CloseCode.POLICY_VIOLATION,
            "unknown path: /",
            "unknown path: /",
            id="policy-violation",
        ),
        pytest.param(CloseCode.NORMAL_CLOSURE, "", "", id="normal-closure"),
        pytest.param(CloseCode.NO_STATUS_RCVD, None, "", id="no-status-code"),
        pytest.param(
            CloseCode.INTERNAL_ERROR,
            "internal error",
            "internal error",
            id="internal-error",
        ),
    ],
)
def test_gives_the_reason_of_a_deliberate_close(
    code: int | None, reason: str | None, expected: str | None
) -> None:
    assert deliberate_close_reason(code, reason) == expected


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
