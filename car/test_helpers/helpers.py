import contextlib
import http.client
import socket
from collections.abc import Iterator
from typing import NamedTuple

from pytest_embedded import Dut

# Mirrored from WEB_SERVER_*_PORT in components/web_server/include/web_server.hpp
DRIVE_PORT = 80
CAMERA_PORT = 81
TELEMETRY_PORT = 82

OPEN_TIMEOUT_S = 8.0
CLOSE_TIMEOUT_S = 10.0


class Endpoint(NamedTuple):
    host: str
    port: int
    path: str
    scheme: str = 'ws'

    @property
    def uri(self) -> str:
        return f'{self.scheme}://{self.host}:{self.port}{self.path}'


class CarEndpoints(NamedTuple):
    drive: Endpoint
    camera: Endpoint
    telemetry: Endpoint


def car_endpoints(
    host: str, drive_port: int = DRIVE_PORT, camera_port: int = CAMERA_PORT, telemetry_port: int = TELEMETRY_PORT
) -> CarEndpoints:
    return CarEndpoints(
        drive=Endpoint(host, drive_port, '/'),
        camera=Endpoint(host, camera_port, '/stream', 'http'),
        telemetry=Endpoint(host, telemetry_port, '/telemetry'),
    )


@contextlib.contextmanager
def open_stream(endpoint: Endpoint, sock: socket.socket | None = None) -> Iterator[http.client.HTTPResponse]:
    connection = http.client.HTTPConnection(endpoint.host, endpoint.port, timeout=OPEN_TIMEOUT_S)
    connection.sock = sock
    try:
        connection.request('GET', endpoint.path)
        yield connection.getresponse()
    finally:
        connection.close()


def read_part(response: http.client.HTTPResponse) -> tuple[dict[str, str], bytes]:
    headers: dict[str, str] = {}
    while True:
        line = response.readline()
        if not line:
            raise ConnectionError('the Camera stream ended')
        line = line.strip()
        if not line and headers:
            break
        if not line or line.startswith(b'--'):
            continue
        name, _, value = line.decode().partition(':')
        headers[name.strip().lower()] = value.strip()
    length = int(headers['content-length'])
    jpeg = response.read(length)
    if len(jpeg) != length:
        raise ConnectionError('the Camera stream ended mid-part')
    return headers, jpeg


def get_dut_ip(dut: Dut) -> str:
    match = dut.expect(r'sta ip: (\d+\.\d+\.\d+\.\d+)', timeout=30)
    return match.group(1).decode()
