import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from controller.command import Command
from controller.senders import send_command

from .conftest import counter_values_by_command


class _ConnectionStub:
    """Stand-in for a `websockets` client connection that accepts every send."""

    async def send(self, _payload: str, /) -> None:
        """Accept `_payload` instead of writing it to a socket."""


@pytest.mark.asyncio
async def test_records_a_metric_for_every_command_sent(
    reader: InMemoryMetricReader,
) -> None:
    connection = _ConnectionStub()

    await send_command(connection, (Command.TURN_LEFT, 50))
    await send_command(connection, (Command.BRAKE, None))

    assert counter_values_by_command(reader, "dust_mite_commands_sent") == {
        "TURN_LEFT": 1,
        "BRAKE": 1,
    }
