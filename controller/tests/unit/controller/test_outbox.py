import asyncio

import pytest

from controller.outbox import Broadcast, Inbox, Outbox


@pytest.mark.asyncio
async def test_every_outbox_receives_a_published_message() -> None:
    frames = Broadcast[str]()
    async with Outbox(frames) as first, Outbox(frames) as second:
        frames.publish("frame")

        assert [await anext(first), await anext(second)] == ["frame", "frame"]


@pytest.mark.asyncio
async def test_a_lagging_outbox_receives_only_the_newest_message_of_each_source() -> (
    None
):
    commands, states = Broadcast[str](), Broadcast[str]()
    async with Outbox(commands, states) as outbox:
        commands.publish("stale")
        commands.publish("newest")
        states.publish("only")

        assert [await anext(outbox), await anext(outbox)] == ["newest", "only"]


@pytest.mark.asyncio
async def test_an_inbox_receives_every_message_in_order() -> None:
    readings = Broadcast[int]()
    async with Inbox(readings) as inbox:
        readings.publish(3)
        readings.publish(7)

        assert [await anext(inbox), await anext(inbox)] == [3, 7]


@pytest.mark.asyncio
async def test_a_message_published_before_the_outbox_opens_is_not_received() -> None:
    frames = Broadcast[str]()
    frames.publish("early")
    async with Outbox(frames) as outbox:
        frames.publish("late")

        assert await anext(outbox) == "late"


@pytest.mark.asyncio
async def test_leaving_the_outbox_stops_receiving() -> None:
    frames = Broadcast[str]()
    async with Outbox(frames) as outbox:
        pass
    frames.publish("after")

    assert [message async for message in outbox] == []


@pytest.mark.asyncio
async def test_cancelling_the_holder_of_the_outbox_stops_receiving() -> None:
    frames = Broadcast[str]()
    outbox = Outbox(frames)
    opened = asyncio.Event()

    async def hold() -> None:
        async with outbox:
            opened.set()
            await asyncio.Event().wait()

    holder = asyncio.create_task(hold())
    await opened.wait()
    holder.cancel()
    await asyncio.wait([holder])
    frames.publish("after")

    assert [message async for message in outbox] == []


@pytest.mark.asyncio
async def test_a_closed_outbox_cannot_be_reopened() -> None:
    outbox = Outbox(Broadcast[str]())
    async with outbox:
        pass

    with pytest.raises(RuntimeError):
        async with outbox:
            pass
