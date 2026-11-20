"""Guards that a phase's step outputs reach `$GITHUB_OUTPUT` whole."""

import io
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from afk.__main__ import main, write_outputs


def gh_stub(args: Sequence[str], _env: Mapping[str, str]) -> str:
    assert args[:3] == ["gh", "api", "graphql"]
    return json.dumps({"data": {"repository": {"issue": {"blocking": {"nodes": []}}}}})


def read_outputs(text: str) -> dict[str, str]:
    """Parse a step output file as the runner does, in both of its forms."""
    lines = iter(text.splitlines())
    outputs = {}
    for line in lines:
        equals, heredoc = line.find("="), line.find("<<")
        if equals != -1 and (heredoc == -1 or equals < heredoc):
            name, value = line.split("=", 1)
            outputs[name] = value
        else:
            name, delimiter = line.split("<<", 1)
            value_lines = []
            for value_line in lines:
                if value_line == delimiter:
                    break
                value_lines.append(value_line)
            outputs[name] = "\n".join(value_lines)
    return outputs


def delimiters(text: str) -> list[str]:
    return [line.split("<<", 1)[1] for line in text.splitlines() if "<<" in line]


class TestMain:
    def test_writes_the_phase_outputs_to_the_step_output_file(
        self, tmp_path: Path
    ) -> None:
        output = tmp_path / "output"
        output.write_text("earlier=1\n")
        env = {
            "AFK_APP_TOKEN": "app-token",
            "AFK_WORKFLOW_TOKEN": "workflow-token",
            "AFK_BLOCKING_TICKET": "12",
            "AFK_BOT_ID": "900",
            "AFK_DRY_RUN": "true",
            "GH_REPO": "owner/repo",
            "GITHUB_OUTPUT": str(output),
        }

        main(["promote-queued"], gh_stub, env)

        assert read_outputs(output.read_text()) == {"earlier": "1", "effects": "[]"}

    def test_rejects_an_unknown_phase(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            main(["unknown"], gh_stub, {"GITHUB_OUTPUT": str(tmp_path / "output")})


class TestWriteOutputs:
    def test_keeps_a_multiline_value_whole(self) -> None:
        output = io.StringIO()

        write_outputs(output, {"body": "first line\ninjected=1"})

        assert read_outputs(output.getvalue()) == {"body": "first line\ninjected=1"}

    def test_uses_a_new_delimiter_for_each_write(self) -> None:
        output = io.StringIO()

        write_outputs(output, {"first": "1"})
        write_outputs(output, {"second": "2"})

        first, second = delimiters(output.getvalue())
        assert first != second
