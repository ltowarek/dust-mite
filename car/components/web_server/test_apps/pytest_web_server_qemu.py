from pytest_embedded import Dut


def test_web_server_qemu(dut: Dut) -> None:
    dut.expect_unity_test_output()
