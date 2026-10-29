import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable

import pytest

from controller.outbox import Broadcast, Inbox, Outbox, RefCountFeed


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


class _ReadSpy:
    """A feed's `read` that records how many start, run at once and end."""

    def __init__(self, *, closing_s: float = 0.0) -> None:
        self.started = 0
        self.running = 0
        self.most_running = 0
        self.ended = asyncio.Event()
        self._closing_s = closing_s

    async def __call__(self, _publish: Callable[[str], None]) -> None:
        self.started += 1
        self.running += 1
        self.most_running = max(self.most_running, self.running)
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(self._closing_s)
            self.running -= 1
            self.ended.set()


@contextlib.asynccontextmanager
async def _supervised(feed: RefCountFeed[str]) -> AsyncIterator[None]:
    supervisor = asyncio.create_task(feed.supervise())
    try:
        yield
    finally:
        supervisor.cancel()
        await asyncio.wait([supervisor])


async def _settle() -> None:
    await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_watchers_share_one_read() -> None:
    read = _ReadSpy()
    feed = RefCountFeed(read)
    async with _supervised(feed), feed.watching(), feed.watching():
        await _settle()

    assert read.most_running == 1


@pytest.mark.asyncio
async def test_the_read_ends_after_the_last_watcher_leaves() -> None:
    read = _ReadSpy()
    feed = RefCountFeed(read)
    async with _supervised(feed):
        async with feed.watching():
            await _settle()
        await asyncio.wait_for(read.ended.wait(), timeout=1)

        assert read.running == 0


@pytest.mark.asyncio
async def test_a_new_read_waits_for_the_previous_one_to_end() -> None:
    read = _ReadSpy(closing_s=0.05)
    feed = RefCountFeed(read)
    async with _supervised(feed):
        async with feed.watching():
            await _settle()
        await _settle()
        async with feed.watching():
            await asyncio.sleep(0.1)

    assert read.most_running == 1


@pytest.mark.asyncio
async def test_a_watcher_returning_at_once_keeps_the_read() -> None:
    read = _ReadSpy()
    feed = RefCountFeed(read)
    async with _supervised(feed):
        async with feed.watching():
            await _settle()
        async with feed.watching():
            await _settle()

    assert read.started == 1


@pytest.mark.asyncio
async def test_a_watcher_receives_what_the_read_publishes() -> None:
    async def read(publish: Callable[[str], None]) -> None:
        publish("frame")
        await asyncio.Event().wait()

    feed = RefCountFeed(read)
    async with _supervised(feed), feed.watching() as outbox:
        received = await anext(outbox)

    assert received == "frame"


@pytest.mark.asyncio
async def test_an_error_from_the_read_stops_the_supervisor() -> None:
    async def read(_publish: Callable[[str], None]) -> None:
        raise ValueError

    feed = RefCountFeed(read)
    supervisor = asyncio.create_task(feed.supervise())
    with pytest.raises(ExceptionGroup) as raised:
        async with feed.watching():
            await supervisor

    assert raised.group_contains(ValueError)
