"""Processing of Camera frames from the car."""

import cv2
import numpy as np
from opentelemetry import trace

from .metrics import record_camera_frame_processed

tracer = trace.get_tracer(__name__)


@tracer.start_as_current_span("streamer.process_camera_frame")
def process_camera_frame(camera_frame: bytes) -> bytes:
    """Process one Camera frame, a JPEG."""
    span = trace.get_current_span()
    span.set_attribute("input_size_bytes", len(camera_frame))

    arr = np.frombuffer(camera_frame, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)

    img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    result = cv2.imencode(".jpg", img)[1].tobytes()

    span.set_attribute("output_size_bytes", len(result))
    record_camera_frame_processed()
    return result
