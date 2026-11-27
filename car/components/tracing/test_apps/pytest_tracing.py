from pytest_embedded import Dut


class TestTracing:
    def test_tracing(self, dut: Dut) -> None:
        dut.expect_unity_test_output()
