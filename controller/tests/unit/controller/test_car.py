from controller.car import prepare_drive_command
from controller.command import Command


class TestPrepareDriveCommand:
    def test_a_drive_command_keeps_the_command_and_value(self) -> None:
        command = {"command": Command.ADVANCE.value, "value": 50}

        assert prepare_drive_command(command).items() >= command.items()
