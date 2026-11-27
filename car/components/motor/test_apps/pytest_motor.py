from pytest_embedded import Dut


class TestMotor:
    def test_motor(self, dut: Dut) -> None:
        dut.expect_unity_test_output(timeout=120)
