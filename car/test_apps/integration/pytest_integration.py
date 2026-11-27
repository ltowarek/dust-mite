import asyncio
import json

import websockets
from pytest_embedded import Dut

from helpers import car_endpoints, get_dut_ip, open_stream, read_part


class TestDriveEndpoint:
    def test_command_pipeline(self, dut: Dut) -> None:
        """Command JSON -> web server -> command queue -> motor task."""
        car = car_endpoints(get_dut_ip(dut))
        dut.expect(r'Serving every endpoint', timeout=70)

        async def run():
            async with websockets.connect(car.drive.uri) as ws:
                await ws.send(json.dumps({"command": 3, "value": 0}))

        asyncio.run(run())
        dut.expect(r'JSON=\{"command": 3, "value": 0\}', timeout=5)


class TestTelemetryEndpoint:
    def test_telemetry_pipeline(self, dut: Dut) -> None:
        """Sensors -> telemetry task -> web server -> WebSocket client."""
        car = car_endpoints(get_dut_ip(dut))
        dut.expect(r'Serving every endpoint', timeout=70)

        async def run():
            messages = []
            async with websockets.connect(car.telemetry.uri) as ws:
                for _ in range(3):
                    raw = await asyncio.wait_for(ws.recv(), timeout=5)
                    messages.append(json.loads(raw))
            return messages

        messages = asyncio.run(run())
        assert len(messages) == 3

        required = {'timestamp', 'rssi', 'speed', 'accelerometer',
                    'magnetometer', 'gyroscope', 'distance_ahead'}
        for message in messages:
            assert required <= message.keys(), f'missing keys: {required - message.keys()}'
            for vec in ('accelerometer', 'magnetometer', 'gyroscope'):
                assert {'x', 'y', 'z'} <= message[vec].keys()

        timestamps = [message['timestamp'] for message in messages]
        assert all(isinstance(ts, str) and len(ts) > 0 for ts in timestamps), \
            'timestamps must be non-empty strings'


class TestCameraEndpoint:
    def test_stream_pipeline(self, dut: Dut) -> None:
        """Camera -> frame queue -> web server -> MJPEG parts over HTTP."""
        car = car_endpoints(get_dut_ip(dut))
        dut.expect(r'Serving every endpoint', timeout=70)

        with open_stream(car.camera) as stream:
            frames = [read_part(stream)[1] for _ in range(10)]

        for i, frame in enumerate(frames):
            assert frame[:2] == b'\xff\xd8', f'frame {i}: missing JPEG SOI'
            assert frame[-2:] == b'\xff\xd9', f'frame {i}: missing JPEG EOI'
