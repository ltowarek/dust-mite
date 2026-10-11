import socket

import pytest
from helpers import get_dut_ip
from pytest_embedded import Dut


def _under_qemu(config: pytest.Config) -> bool:
    return 'qemu' in (config.getoption('embedded_services', None) or '')


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line('markers', 'dut(reason=None): requires a real, connected device')


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if not _under_qemu(config):
        return
    for item in items:
        marker = item.get_closest_marker('dut')
        if marker is None:
            continue
        reason = marker.kwargs.get('reason', 'requires a real, connected device')
        item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture
def qemu_http_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


@pytest.fixture
def qemu_cli_args(qemu_http_port: int) -> str:
    return (
        '-nographic -machine esp32s3 -m 4M '
        f'-nic user,model=open_eth,hostfwd=tcp:127.0.0.1:{qemu_http_port}-:80'
    )


@pytest.fixture
def car_address(request: pytest.FixtureRequest, dut: Dut, qemu_http_port: int) -> tuple[str, int]:
    if _under_qemu(request.config):
        dut.expect(r'eth ip: ', timeout=30)
        return '127.0.0.1', qemu_http_port
    return get_dut_ip(dut), 80
