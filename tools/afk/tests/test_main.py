"""Guards that a phase's step outputs reach `$GITHUB_OUTPUT`."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from afk.__main__ import main


def gh_stub(args: Sequence[str], _env: Mapping[str, str]) -> str:
    assert args[:3] == ["gh", "api", "graphql"]
    return json.dumps({"data": {"repository": {"issue": {"blocking": {"nodes": []}}}}})


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

        assert output.read_text() == "earlier=1\neffects=[]\n"

    def test_rejects_an_unknown_phase(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            main(["unknown"], gh_stub, {"GITHUB_OUTPUT": str(tmp_path / "output")})
