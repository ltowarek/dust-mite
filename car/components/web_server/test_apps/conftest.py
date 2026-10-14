import contextlib
import socket

import pytest
from helpers import CAMERA_PORT, DRIVE_PORT, TELEMETRY_PORT, CarEndpoints, car_endpoints, get_dut_ip
from pytest_embedded import Dut

_CAR_PORTS = (DRIVE_PORT, CAMERA_PORT, TELEMETRY_PORT)


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
def qemu_http_ports() -> dict[int, int]:
    """A free local port for each car port. All are held open until each is chosen, so no two are the same."""
    with contextlib.ExitStack() as stack:
        sockets = {car: stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) for car in _CAR_PORTS}
        for s in sockets.values():
            s.bind(('127.0.0.1', 0))
        return {car: s.getsockname()[1] for car, s in sockets.items()}


@pytest.fixture
def qemu_cli_args(qemu_http_ports: dict[int, int]) -> str:
    forwards = ','.join(f'hostfwd=tcp:127.0.0.1:{local}-:{car}' for car, local in qemu_http_ports.items())
    return f'-nographic -machine esp32s3 -m 4M -nic user,model=open_eth,{forwards}'


@pytest.fixture
def car(request: pytest.FixtureRequest, dut: Dut, qemu_http_ports: dict[int, int]) -> CarEndpoints:
    if _under_qemu(request.config):
        dut.expect(r'eth ip: ', timeout=30)
        return car_endpoints(
            '127.0.0.1',
            drive_port=qemu_http_ports[DRIVE_PORT],
            camera_port=qemu_http_ports[CAMERA_PORT],
            telemetry_port=qemu_http_ports[TELEMETRY_PORT],
        )
    return car_endpoints(get_dut_ip(dut))
