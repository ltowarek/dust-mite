"""Command domain type shared between input backends and command senders."""

from enum import Enum


class Command(Enum):
    """Car commands."""

    ADVANCE = 1
    RETREAT = 2
    BRAKE = 3
    TURN_LEFT = 4
    TURN_RIGHT = 5
    LOOK_HORIZONTALLY = 6
    LOOK_VERTICALLY = 7
