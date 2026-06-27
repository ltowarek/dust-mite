from helpers import collect_gcda
from pytest_embedded import Dut


def test_telemetry_coverage(dut: Dut) -> None:
    dut.expect_unity_test_output()
    collect_gcda(dut)
