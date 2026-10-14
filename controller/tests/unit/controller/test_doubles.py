"""Test doubles shared by the controller unit tests."""

from controller.command import Command

__test__ = False


class CommandSenderSpy:
    """Command sender that records sent commands instead of transmitting them."""

    def __init__(self) -> None:
        """Initialize the object."""
        self.sent: list[tuple[Command, int | None]] = []

    def send(self, command: Command, value: int | None) -> None:
        """Record a command instead of sending it anywhere."""
        self.sent.append((command, value))


class SubscriberSpy[T]:
    """`Subject` subscriber that records every message published to it."""

    def __init__(self) -> None:
        """Initialize the object."""
        self.messages: list[T] = []

    def __call__(self, message: T) -> None:
        """Record `message`."""
        self.messages.append(message)
