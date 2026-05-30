from pytest_embedded import Dut


def get_dut_ip(dut: Dut) -> str:
    match = dut.expect(r'sta ip: (\d+\.\d+\.\d+\.\d+)', timeout=30)
    return match.group(1).decode()
