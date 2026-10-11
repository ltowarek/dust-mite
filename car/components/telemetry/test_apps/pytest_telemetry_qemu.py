from pytest_embedded import Dut


def test_telemetry(dut: Dut) -> None:
    dut.expect_unity_test_output()
