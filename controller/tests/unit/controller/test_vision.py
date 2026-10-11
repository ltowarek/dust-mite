import cv2
import numpy as np

from controller.vision import process_frame

_GRAYSCALE_DIMENSIONS = 2


def _colour_jpeg() -> bytes:
    image = np.zeros((8, 8, 3), dtype=np.uint8)
    image[:, :, 2] = 255
    return cv2.imencode(".jpg", image)[1].tobytes()


def test_turns_a_colour_frame_into_a_grayscale_jpeg() -> None:
    processed = cv2.imdecode(
        np.frombuffer(process_frame(_colour_jpeg()), dtype=np.uint8),
        cv2.IMREAD_UNCHANGED,
    )

    assert processed.ndim == _GRAYSCALE_DIMENSIONS
