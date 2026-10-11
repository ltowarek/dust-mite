"""Publish/subscribe fan-out of one feed to any number of subscribers."""

import contextlib
import threading
from collections.abc import Callable, Iterator
from typing import Any


class Subject:
    """Delivers every published message to each current subscriber.

    `on_active` runs when the first subscriber arrives and `on_idle` after the
    last one leaves, so an upstream feed only needs to run while someone is
    listening. Both run on the subscribing/unsubscribing thread, serialized
    against each other.
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
        self._lifecycle_lock = threading.Lock()
        self._subscribers_lock = threading.Lock()
        self._subscribers: list[Callable[[Any], None]] = []

    @contextlib.contextmanager
    def subscription(self, callback: Callable[[Any], None]) -> Iterator[None]:
        """Call `callback` with every message published while the context is open."""
        self._subscribe(callback)
        try:
            yield
        finally:
            self._unsubscribe(callback)

    def publish(self, message: Any) -> None:  # noqa: ANN401 - subjects carry any payload
        """Deliver `message` to every current subscriber."""
        with self._subscribers_lock:
            subscribers = list(self._subscribers)
        for callback in subscribers:
            callback(message)

    def _subscribe(self, callback: Callable[[Any], None]) -> None:
        with self._lifecycle_lock:
            with self._subscribers_lock:
                first = not self._subscribers
                self._subscribers.append(callback)
            if first and self._on_active is not None:
                self._on_active()

    def _unsubscribe(self, callback: Callable[[Any], None]) -> None:
        with self._lifecycle_lock:
            with self._subscribers_lock:
                self._subscribers.remove(callback)
                last = not self._subscribers
            if last and self._on_idle is not None:
                self._on_idle()
