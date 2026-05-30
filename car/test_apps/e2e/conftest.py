import pathlib

import pytest


@pytest.fixture(scope='session')
def app_path():
    return str(pathlib.Path(__file__).parent.parent.parent)  # car/
