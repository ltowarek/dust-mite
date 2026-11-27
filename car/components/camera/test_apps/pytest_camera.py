from pytest_embedded import Dut


class TestCamera:
    def test_camera(self, dut: Dut) -> None:
        dut.expect_unity_test_output()
