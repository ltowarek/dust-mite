from typing import NamedTuple

from pytest_embedded import Dut

# Mirrored from WEB_SERVER_*_PORT in components/web_server/include/web_server.hpp
DRIVE_PORT = 80
CAMERA_PORT = 81
TELEMETRY_PORT = 82


class Endpoint(NamedTuple):
    host: str
    port: int
    path: str

    @property
    def uri(self) -> str:
        return f'ws://{self.host}:{self.port}{self.path}'


class CarEndpoints(NamedTuple):
    drive: Endpoint
    camera: Endpoint
    telemetry: Endpoint


def car_endpoints(
    host: str, drive_port: int = DRIVE_PORT, camera_port: int = CAMERA_PORT, telemetry_port: int = TELEMETRY_PORT
) -> CarEndpoints:
    return CarEndpoints(
        drive=Endpoint(host, drive_port, '/'),
        camera=Endpoint(host, camera_port, '/stream'),
        telemetry=Endpoint(host, telemetry_port, '/telemetry'),
    )


def get_dut_ip(dut: Dut) -> str:
    match = dut.expect(r'sta ip: (\d+\.\d+\.\d+\.\d+)', timeout=30)
    return match.group(1).decode()
