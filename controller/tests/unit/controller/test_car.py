import base64

from controller.car import camera_frame_jpeg, prepare_drive_command
from controller.command import Command

_JPEG = b"\xff\xd8\xff\xd9"


def test_reads_the_jpeg_from_a_camera_message() -> None:
    message = {"data": base64.b64encode(_JPEG).decode("ascii")}

    assert camera_frame_jpeg(message) == _JPEG


def test_a_drive_command_keeps_the_command_and_value() -> None:
    command = {"command": Command.ADVANCE.value, "value": 50}

    assert prepare_drive_command(command).items() >= command.items()
