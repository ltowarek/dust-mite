import pytest

from controller.outbox import Outbox
from controller.subject import Subject


@pytest.mark.asyncio
async def test_takes_only_the_newest_message_of_each_source() -> None:
    commands, states = Subject[str](), Subject[str]()
    with Outbox(commands, states) as outbox:
        commands.publish("stale")
        commands.publish("newest")
        states.publish("only")

        assert await outbox.take() == ["newest", "only"]
