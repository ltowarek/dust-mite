import contextlib
import socket

import pytest
from helpers import CAMERA_PORT, DRIVE_PORT, TELEMETRY_PORT, CarEndpoints, car_endpoints, get_dut_ip
from pytest_embedded import Dut

# In the order of CarEndpoints.
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
def qemu_http_ports() -> tuple[int, ...]:
    """Free local ports, one per car port. All are held open until each is chosen, so no two are the same."""
    with contextlib.ExitStack() as stack:
        sockets = [stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) for _ in _CAR_PORTS]
        for s in sockets:
            s.bind(('127.0.0.1', 0))
        return tuple(s.getsockname()[1] for s in sockets)


@pytest.fixture
def qemu_cli_args(qemu_http_ports: tuple[int, ...]) -> str:
    forwards = ','.join(
        f'hostfwd=tcp:127.0.0.1:{local}-:{car}' for local, car in zip(qemu_http_ports, _CAR_PORTS, strict=True)
    )
    return f'-nographic -machine esp32s3 -m 4M -nic user,model=open_eth,{forwards}'


@pytest.fixture
def car(request: pytest.FixtureRequest, dut: Dut, qemu_http_ports: tuple[int, ...]) -> CarEndpoints:
    if _under_qemu(request.config):
        dut.expect(r'eth ip: ', timeout=30)
        return car_endpoints('127.0.0.1', *qemu_http_ports)
    return car_endpoints(get_dut_ip(dut))
