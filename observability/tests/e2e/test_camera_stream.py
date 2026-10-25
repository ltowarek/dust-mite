"""Camera frames must reach a viewer at the camera's rate, cheaply for the car."""

import dataclasses
import http.client
import statistics
import time
import urllib.parse
from collections.abc import Callable
from typing import Any, cast

import pytest
import requests

from tests.helpers.query import MIMIR_UID, query
from tests.helpers.settings import STACK_SETTINGS

_REASON = (
    "requires the car flashed with sdkconfig.defaults.debug, "
    "streaming through the headless stack"
)
SEND_SPAN = "camera.frame.send"
MESSAGE_SIZE = "messaging.message.envelope.size"
STREAM_TASK = "stream_task"
STREAM_S = 60.0
FRAME_TIMEOUT_S = 5.0
# Spans and metrics are exported in batches well within this.
INGEST_S = 60.0
RecordProperty = Callable[[str, object], None]
MIN_VIEWER_FPS = 22.0
# A send must finish within one frame period or it holds back the camera.
MAX_SEND_P95_MS = 1000 / MIN_VIEWER_FPS
MIN_STACK_FREE_BYTES = 4096


@dataclasses.dataclass(frozen=True)
class StreamWindow:
    start: float
    end: float
    frames: int

    @property
    def fps(self) -> float:
        return self.frames / (self.end - self.start)


@dataclasses.dataclass(frozen=True)
class SendSpan:
    duration_ms: float
    size: int


def _read_part(stream: http.client.HTTPResponse) -> None:
    length = None
    while True:
        line = stream.readline()
        if not line:
            raise EOFError
        line = line.strip()
        if not line and length is not None:
            break
        name, _, value = line.decode().partition(":")
        if name.strip().lower() == "content-length":
            length = int(value)
    stream.read(length)


@pytest.fixture(scope="module")
def window() -> StreamWindow:
    camera = urllib.parse.urlsplit(STACK_SETTINGS.camera_uri)
    viewer = http.client.HTTPConnection(
        camera.hostname or "", camera.port, timeout=FRAME_TIMEOUT_S
    )
    start = time.time()
    frames = 0
    try:
        viewer.request("GET", camera.path)
        stream = viewer.getresponse()
        while time.time() < start + STREAM_S:
            _read_part(stream)
            frames += 1
    finally:
        viewer.close()
    end = time.time()
    time.sleep(INGEST_S)
    return StreamWindow(start, end, frames)


def _tempo(path: str, params: dict[str, str | int] | None = None) -> dict[str, Any]:
    response = requests.get(
        f"{STACK_SETTINGS.grafana_url}/api/datasources/proxy/uid/tempo{path}",
        params=params,
        headers={"Accept": "application/json"},
        timeout=60,
    )
    response.raise_for_status()
    return cast("dict[str, Any]", response.json())


@pytest.fixture(scope="module")
def send_spans(window: StreamWindow) -> list[SendSpan]:
    # Search returns at most 100 spans per trace, so read each matching trace whole.
    search = _tempo(
        "/api/search",
        {
            "q": f'{{resource.service.name="dust-mite-car" && name="{SEND_SPAN}"}}',
            "start": int(window.start),
            "end": int(window.end) + 1,
            "limit": 100,
        },
    )
    spans = []
    for found in search.get("traces", []):
        trace = _tempo(f"/api/traces/{found['traceID']}")
        for batch in trace["batches"]:
            for scope in batch["scopeSpans"]:
                for span in scope["spans"]:
                    started = int(span["startTimeUnixNano"]) / 1e9
                    if span["name"] != SEND_SPAN or not (
                        window.start <= started <= window.end
                    ):
                        continue
                    attrs = {a["key"]: a["value"] for a in span["attributes"]}
                    ended = int(span["endTimeUnixNano"]) / 1e9
                    spans.append(
                        SendSpan(
                            duration_ms=(ended - started) * 1000,
                            size=int(attrs[MESSAGE_SIZE]["intValue"]),
                        )
                    )
    return spans


@pytest.mark.dut(reason=_REASON)
def test_viewer_receives_camera_rate(
    window: StreamWindow, record_property: RecordProperty
) -> None:
    record_property("viewer_fps", round(window.fps, 1))
    assert window.fps >= MIN_VIEWER_FPS


@pytest.mark.dut(reason=_REASON)
def test_car_sends_frames_promptly(
    send_spans: list[SendSpan], record_property: RecordProperty
) -> None:
    durations = [s.duration_ms for s in send_spans]
    percentiles = statistics.quantiles(durations, n=100)
    p95 = percentiles[94]
    record_property("send_spans", len(send_spans))
    record_property("send_p50_ms", round(percentiles[49], 2))
    record_property("send_p95_ms", round(p95, 2))
    record_property(
        "bytes_per_frame", round(statistics.mean(s.size for s in send_spans))
    )
    assert p95 <= MAX_SEND_P95_MS


@pytest.mark.dut(reason=_REASON)
def test_stream_task_keeps_stack_headroom(
    window: StreamWindow, record_property: RecordProperty
) -> None:
    seconds = int(window.end - window.start) + 1
    selector = f'dust_mite_task_stack_min_free_bytes{{task="{STREAM_TASK}"}}'
    result = query(
        MIMIR_UID,
        "prometheus",
        {"expr": f"min_over_time({selector}[{seconds}s])", "instant": True},
        time_range=str(int(window.start * 1000)),
        until=str(int(window.end * 1000)),
    )
    min_free = int(cast("float", result["frames"][0]["data"]["values"][1][0]))
    record_property("stream_task_stack_min_free_bytes", min_free)
    assert min_free >= MIN_STACK_FREE_BYTES
