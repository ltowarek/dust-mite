"""Processing of camera frames from the car."""

import cv2
import numpy as np
from opentelemetry import trace

from .metrics import record_frame

tracer = trace.get_tracer(__name__)


@tracer.start_as_current_span("streamer.process_frame")
def process_frame(frame: bytes) -> bytes:
    """Process camera frame."""
    span = trace.get_current_span()
    span.set_attribute("input_size_bytes", len(frame))

    arr = np.frombuffer(frame, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)

    img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    result = cv2.imencode(".jpg", img)[1].tobytes()

    span.set_attribute("output_size_bytes", len(result))
    record_frame()
    return result
