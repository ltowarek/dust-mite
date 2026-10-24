"""The stream must keep the camera's rate while the car's debug metrics are collected.

Needs the test app built with sdkconfig.defaults.all into build_all/.
"""

import pytest
from pytest_embedded import Dut


@pytest.fixture(autouse=True)
def _all_build(dut: Dut) -> None:
    if dut.app.sdkconfig.get('SYSTEM_METRICS_TASK_STATS_ENABLED') is not True:
        pytest.skip('needs the all build (sdkconfig.defaults.all)')


@pytest.mark.dut(reason='measures the frame rate of the real camera')
def test_stream_keeps_the_camera_rate(dut: Dut) -> None:
    dut.run_single_board_case('stream_keeps_the_camera_rate', reset=True, timeout=60)
