import logging
from collections.abc import Generator

import pytest


@pytest.fixture
def root_logger() -> Generator[logging.Logger, None, None]:
    """The root logger, with its handler list restored after the test."""
    logger = logging.getLogger()
    original_handlers = list(logger.handlers)
    yield logger
    logger.handlers = original_handlers
