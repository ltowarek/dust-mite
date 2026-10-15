import threading
from collections.abc import Iterator

import pytest

from .test_doubles import CollectorServer, CollectorSpy


@pytest.fixture
def collector() -> Iterator[CollectorServer]:
    server = CollectorServer(("127.0.0.1", 0), CollectorSpy)
    server.received = []
    server.response_status = 200
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join()
