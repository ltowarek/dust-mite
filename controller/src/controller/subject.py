"""Observables, and the Subject that fans one out to any number of subscribers."""

import contextlib
import logging
from collections.abc import Callable, Iterator
from typing import Protocol

logger = logging.getLogger(__name__)


class Observable[T](Protocol):
    """Messages that any number of callbacks can subscribe to."""

    def subscription(
        self, callback: Callable[[T], None]
    ) -> contextlib.AbstractContextManager[None]:
        """Call `callback` with each message while the context is open."""
        ...


class Subject[T]:
    """An Observable that can also be published to, delivering to every subscriber.

    `on_active` runs when the first subscriber arrives and `on_idle` after the
    last one leaves: the hooks a RefCount connects and disconnects its upstream
    feed on. It is confined to one thread, the event loop's.
    """

    def __init__(
        self,
        *,
        on_active: Callable[[], None] | None = None,
        on_idle: Callable[[], None] | None = None,
    ) -> None:
        """Initialize the object."""
        self._on_active = on_active
        self._on_idle = on_idle
        self._subscribers: list[Callable[[T], None]] = []

    @contextlib.contextmanager
    def subscription(self, callback: Callable[[T], None]) -> Iterator[None]:
        """Call `callback` with every message published while the context is open."""
        self._subscribe(callback)
        try:
            yield
        finally:
            self._unsubscribe(callback)

    def publish(self, message: T) -> None:
        """Deliver `message` to every current subscriber, logging any that raises."""
        for callback in list(self._subscribers):
            try:
                callback(message)
            except Exception:
                logger.exception("A subscriber failed on a published message")

    def _subscribe(self, callback: Callable[[T], None]) -> None:
        first = not self._subscribers
        self._subscribers.append(callback)
        if first and self._on_active is not None:
            self._on_active()

    def _unsubscribe(self, callback: Callable[[T], None]) -> None:
        self._subscribers.remove(callback)
        if not self._subscribers and self._on_idle is not None:
            self._on_idle()
