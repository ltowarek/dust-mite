"""The AFK loop's state labels."""

from enum import StrEnum


class Label(StrEnum):
    """The AFK loop's state labels."""

    QUEUED = "afk:queued"
    IN_PROGRESS = "afk:in-progress"
    BLOCKED = "afk:blocked"
