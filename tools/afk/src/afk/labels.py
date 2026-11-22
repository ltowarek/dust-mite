"""The AFK loop's state labels."""

from enum import StrEnum


class Label(StrEnum):
    """The AFK loop's state labels."""

    QUEUED = "afk:queued"
    IN_PROGRESS = "afk:in-progress"
    BLOCKED = "afk:blocked"


def needs_car(variant: str) -> str:
    """Return the label that hands a change to a car agent session on `variant`."""
    return f"needs-car:{variant}"
