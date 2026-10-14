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
