from pytest_embedded import Dut


class TestTelemetry:
    def test_telemetry(self, dut: Dut) -> None:
        dut.expect_unity_test_output()
