"""Test doubles shared by the controller unit and integration tests."""

__test__ = False


class SubscriberSpy[T]:
    """`Subject` subscriber that records every message published to it."""

    def __init__(self) -> None:
        """Initialize the object."""
        self.messages: list[T] = []

    def __call__(self, message: T) -> None:
        """Record `message`."""
        self.messages.append(message)
