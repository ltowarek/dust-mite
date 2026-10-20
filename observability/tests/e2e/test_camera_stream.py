"""Camera frames must reach a viewer at the camera's rate, cheaply for the car."""

import dataclasses
import statistics
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any, cast

import pytest
import requests
from websockets.sync.client import connect

from tests.helpers.producers import PROFILE_TYPE
from tests.helpers.query import MIMIR_UID, PYROSCOPE_UID, query
from tests.helpers.settings import STACK_SETTINGS

_REASON = (
    "requires the car flashed with sdkconfig.defaults.debug, "
    "streaming through the headless stack"
)
SEND_SPAN = "camera.frame.send"
MESSAGE_SIZE = "camera.part.size"
STREAM_TASK = "stream_task"
STREAM_S = 60.0
FRAME_TIMEOUT_S = 5.0
# Spans, metrics and profiles are exported in batches well within this.
INGEST_S = 60.0
TOP_FUNCTIONS = 15
RecordProperty = Callable[[str, object], None]
MIN_VIEWER_FPS = 22.0
# A send must finish within one frame period or it holds back the camera.
MAX_SEND_P95_MS = 1000 / MIN_VIEWER_FPS
MIN_STACK_FREE_BYTES = 4096


@dataclasses.dataclass(frozen=True)
class StreamWindow:
    """When a viewer watched the Camera stream and how many frames it got."""

    start: float
    end: float
    frames: int

    @property
    def fps(self) -> float:
        return self.frames / (self.end - self.start)

    def grafana_range(self) -> dict[str, str]:
        return {
            "time_range": str(int(self.start * 1000)),
            "until": str(int((self.end + INGEST_S) * 1000)),
        }


@dataclasses.dataclass(frozen=True)
class SendSpan:
    """One car send of a Camera frame."""

    duration_ms: float
    size: int
    profile_id: str


@pytest.fixture(scope="module")
def window() -> StreamWindow:
    start = time.time()
    frames = 0
    with connect(STACK_SETTINGS.camera_uri) as viewer:
        while time.time() < start + STREAM_S:
            viewer.recv(timeout=FRAME_TIMEOUT_S)
            frames += 1
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
                            profile_id=attrs["pyroscope.profile.id"]["stringValue"],
                        )
                    )
    return spans


def _flame_graph_rows(result: dict[str, Any]) -> list[tuple[str, int]]:
    """Each flame-graph node's function name and self samples."""
    rows: list[tuple[str, int]] = []
    for frame in result.get("frames", []):
        fields = frame["schema"]["fields"]
        values = frame["data"]["values"]
        names = {f["name"]: i for i, f in enumerate(fields)}
        labels = values[names["label"]]
        enum = fields[names["label"]].get("config", {}).get("type", {}).get("enum")
        if enum is not None:
            labels = [enum["text"][i] for i in labels]
        rows.extend(zip(labels, values[names["self"]], strict=True))
    return rows


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


@pytest.fixture(scope="module")
def send_profile_top(
    window: StreamWindow, send_spans: list[SendSpan]
) -> list[tuple[str, int]]:
    """The functions with the most self samples while the car sent frames."""
    result = query(
        PYROSCOPE_UID,
        "grafana-pyroscope-datasource",
        {
            "queryType": "profile",
            "profileTypeId": PROFILE_TYPE,
            "labelSelector": '{service_name="dust-mite-car"}',
            "spanSelector": [s.profile_id for s in send_spans],
        },
        **window.grafana_range(),
    )
    self_samples: defaultdict[str, int] = defaultdict(int)
    for name, samples in _flame_graph_rows(result):
        self_samples[name] += samples
    return sorted(self_samples.items(), key=lambda kv: -kv[1])[:TOP_FUNCTIONS]


@pytest.mark.dut(reason=_REASON)
def test_send_profile_has_samples(
    send_profile_top: list[tuple[str, int]], record_property: RecordProperty
) -> None:
    record_property("send_profile_top_self", send_profile_top)
    assert send_profile_top


@pytest.mark.dut(reason=_REASON)
def test_send_profile_names_functions(
    send_profile_top: list[tuple[str, int]],
) -> None:
    addresses = [name for name, _ in send_profile_top if name.startswith("0x")]
    assert addresses == []
