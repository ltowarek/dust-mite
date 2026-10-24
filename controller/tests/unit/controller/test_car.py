from controller.car import prepare_drive_command
from controller.command import Command


def test_a_drive_command_keeps_the_command_and_value() -> None:
    command = {"command": Command.ADVANCE.value, "value": 50}

    assert prepare_drive_command(command).items() >= command.items()
