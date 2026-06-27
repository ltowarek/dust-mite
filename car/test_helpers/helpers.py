import base64
from pathlib import Path

from pytest_embedded import Dut


def get_dut_ip(dut: Dut) -> str:
    match = dut.expect(r'sta ip: (\d+\.\d+\.\d+\.\d+)', timeout=30)
    return match.group(1).decode()


def collect_gcda(dut: Dut) -> None:
    base = Path('.')
    current_path: str | None = None
    current_data = bytearray()

    while True:
        match = dut.expect(
            r'GCOV_FILE_START:([^\r\n]+)\r?\n|GCOV_B64:([^\r\n]+)\r?\n|GCOV_FILE_END\r?\n|GCOV_DUMP_DONE\r?\n',
            timeout=60,
        )
        text = match.group(0).decode('ascii').strip()

        if text.startswith('GCOV_FILE_START:'):
            current_path = text[len('GCOV_FILE_START:'):]
            current_data = bytearray()
        elif text.startswith('GCOV_B64:'):
            current_data += base64.b64decode(text[len('GCOV_B64:'):])
        elif text == 'GCOV_FILE_END':
            if current_path is not None:
                dest = base / current_path.lstrip('/')
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(bytes(current_data))
            current_path = None
            current_data = bytearray()
        elif text == 'GCOV_DUMP_DONE':
            return
