import os

from pytest_embedded import Dut


def test_web_server_qemu(dut: Dut) -> None:
    dut.expect_unity_test_output()
    if os.environ.get("COVERAGE_BUILD") == "1":
        dut.expect("GCOV_DUMP_DONE")
