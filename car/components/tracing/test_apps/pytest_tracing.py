from pytest_embedded import Dut


def test_tracing(dut: Dut) -> None:
    dut.expect_unity_test_output()
