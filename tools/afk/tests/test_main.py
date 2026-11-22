"""Guards that `python -m afk <phase>` runs a phase and sets its step outputs."""

import json
from pathlib import Path

import pytest

from afk.__main__ import main
from tests.doubles import GhSpy

NO_BLOCKED_TICKETS = json.dumps(
    {"data": {"repository": {"issue": {"blocking": {"nodes": []}}}}}
)


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

        main(
            ["promote-queued"],
            GhSpy({("gh", "api", "graphql"): NO_BLOCKED_TICKETS}),
            env,
        )

        lines = output.read_text().splitlines()
        delimiter = lines[1].removeprefix("effects<<")
        assert lines == ["earlier=1", f"effects<<{delimiter}", "[]", delimiter]

    def test_rejects_an_unknown_phase(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            main(["unknown"], GhSpy(), {"GITHUB_OUTPUT": str(tmp_path / "output")})
