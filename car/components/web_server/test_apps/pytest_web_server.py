import asyncio
import json

import websockets
from pytest_embedded import Dut


def test_web_server(dut: Dut) -> None:
    match = dut.expect(r'sta ip: (\d+\.\d+\.\d+\.\d+)', timeout=30)
    ip = match.group(1).decode()

    async def run():
        async with websockets.connect(f'ws://{ip}/') as ws:
            await ws.send(json.dumps({"command": 3, "value": 0}))

        async with websockets.connect(f'ws://{ip}/telemetry') as ws:
            pass

        async with websockets.connect(f'ws://{ip}/stream') as ws:
            pass

    asyncio.run(run())
