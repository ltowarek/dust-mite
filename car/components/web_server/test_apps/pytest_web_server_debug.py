"""The debug metrics must leave the stream the camera's rate.

Needs the test app built with sdkconfig.defaults.debug into build_debug/.
"""

import pytest
from pytest_embedded import Dut


@pytest.fixture(autouse=True)
def _debug_build(dut: Dut) -> None:
    if dut.app.sdkconfig.get('SYSTEM_METRICS_TASK_STATS_ENABLED') is not True:
        pytest.skip('needs the debug build (sdkconfig.defaults.debug)')


@pytest.mark.dut(reason='measures the frame rate of the real camera')
def test_stream_keeps_the_camera_rate(dut: Dut) -> None:
    dut.run_single_board_case('stream_keeps_the_camera_rate', reset=True, timeout=60)
