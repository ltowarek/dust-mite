import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--dut",
        action="store_true",
        default=False,
        help="run @pytest.mark.dut tests requiring a real, connected device",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "dut(reason=None): requires a real, connected device"
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--dut"):
        return
    for item in items:
        marker = item.get_closest_marker("dut")
        if marker is None:
            continue
        reason = marker.kwargs.get("reason", "requires --dut")
        item.add_marker(pytest.mark.skip(reason=reason))
