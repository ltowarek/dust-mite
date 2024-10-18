import os


def test_env() -> None:
    assert "ESP32_ADDRESS" in os.environ
