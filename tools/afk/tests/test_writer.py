"""Guards each write's exact command, that a dry run runs none, and the outputs."""

import io
import json
from pathlib import Path

import pytest

from afk.effects import (
    Comment,
    DispatchWorkflow,
    EditLabels,
    Effect,
    React,
)
from afk.writer import Writer, write_outputs
from tests.test_doubles import GhCall, GhSpy, read_outputs

ENV = {
    "AFK_APP_TOKEN": "app-token",
    "AFK_WORKFLOW_TOKEN": "workflow-token",
    "GH_REPO": "owner/repo",
}


EFFECTS: list[Effect] = [
    DispatchWorkflow(workflow="afk-run.yml", inputs={"number": "7"}),
    EditLabels(number=7, add=("afk:in-progress",), remove=("afk:queued",)),
    Comment(number=7, body="Promoted."),
]


class TestWriter:
    class TestWrite:
        @pytest.mark.parametrize(
            ("effect", "args", "token"),
            [
                pytest.param(
                    DispatchWorkflow(
                        workflow="afk-run.yml",
                        inputs={"number": "7", "comment-id": "555"},
                    ),
                    [
                        "gh",
                        "workflow",
                        "run",
                        "afk-run.yml",
                        "-f",
                        "number=7",
                        "-f",
                        "comment-id=555",
                    ],
                    "workflow-token",
                    id="dispatches a workflow with the workflow token",
                ),
                pytest.param(
                    EditLabels(
                        number=7,
                        add=("afk:blocked", "bug"),
                        remove=("afk:queued", "afk:in-progress"),
                    ),
                    [
                        "gh",
                        "issue",
                        "edit",
                        "7",
                        "--add-label",
                        "afk:blocked",
                        "--add-label",
                        "bug",
                        "--remove-label",
                        "afk:queued",
                        "--remove-label",
                        "afk:in-progress",
                    ],
                    "app-token",
                    id="adds and removes labels with the App's token",
                ),
                pytest.param(
                    EditLabels(number=7, remove=("afk:in-progress",)),
                    ["gh", "issue", "edit", "7", "--remove-label", "afk:in-progress"],
                    "app-token",
                    id="only removes labels when it adds none",
                ),
                pytest.param(
                    Comment(number=7, body="Hello `there`"),
                    ["gh", "issue", "comment", "7", "--body", "Hello `there`"],
                    "app-token",
                    id="comments with the App's token",
                ),
                pytest.param(
                    React(comment_id=555, content="eyes"),
                    [
                        "gh",
                        "api",
                        "--method",
                        "POST",
                        "repos/{owner}/{repo}/issues/comments/555/reactions",
                        "-f",
                        "content=eyes",
                    ],
                    "app-token",
                    id="reacts to a comment with the App's token",
                ),
            ],
        )
        def test_runs_each_write_as_its_gh_command_with_its_token(
            self, effect: Effect, args: list[str], token: str, tmp_path: Path
        ) -> None:
            gh = GhSpy()

            Writer(gh, ENV, tmp_path / "output").write(effect)

            assert gh.calls == [GhCall(args, token, "owner/repo")]

        def test_a_dry_run_runs_no_command(self, tmp_path: Path) -> None:
            gh = GhSpy()
            writer = Writer(gh, {**ENV, "AFK_DRY_RUN": "true"}, tmp_path / "output")

            for effect in EFFECTS:
                writer.write(effect)

            assert gh.calls == []

    class TestSetOutput:
        def test_appends_an_output_at_once(self, tmp_path: Path) -> None:
            output = tmp_path / "output"
            output.write_text("earlier=1\n")

            Writer(GhSpy(), ENV, output).set_output("accepted", "true")

            lines = output.read_text().splitlines()
            delimiter = lines[1].removeprefix("accepted<<")
            assert lines == ["earlier=1", f"accepted<<{delimiter}", "true", delimiter]

    class TestReport:
        def test_a_dry_run_reports_its_writes_as_effects(self, tmp_path: Path) -> None:
            output = tmp_path / "output"
            writer = Writer(GhSpy(), {**ENV, "AFK_DRY_RUN": "true"}, output)

            for effect in EFFECTS:
                writer.write(effect)
            writer.report()

            assert json.loads(read_outputs(output)["effects"]) == [
                {
                    "type": "DispatchWorkflow",
                    "workflow": "afk-run.yml",
                    "inputs": {"number": "7"},
                },
                {
                    "type": "EditLabels",
                    "number": 7,
                    "add": ["afk:in-progress"],
                    "remove": ["afk:queued"],
                },
                {"type": "Comment", "number": 7, "body": "Promoted."},
            ]

        def test_a_dry_run_with_no_writes_reports_no_effects(
            self, tmp_path: Path
        ) -> None:
            output = tmp_path / "output"

            Writer(GhSpy(), {**ENV, "AFK_DRY_RUN": "true"}, output).report()

            assert read_outputs(output) == {"effects": "[]"}

        def test_a_real_run_reports_no_effects(self, tmp_path: Path) -> None:
            output = tmp_path / "output"
            writer = Writer(GhSpy(), ENV, output)

            writer.write(Comment(number=7, body="Promoted."))
            writer.report()

            assert read_outputs(output) == {}


class TestWriteOutputs:
    def test_keeps_a_multiline_value_whole(self) -> None:
        output = io.StringIO()

        write_outputs(output, {"body": "first line\ninjected=1"})

        lines = output.getvalue().splitlines()
        delimiter = lines[0].removeprefix("body<<")
        assert lines == [f"body<<{delimiter}", "first line", "injected=1", delimiter]

    def test_uses_a_new_delimiter_for_each_write(self) -> None:
        output = io.StringIO()

        write_outputs(output, {"first": "1"})
        write_outputs(output, {"second": "2"})

        lines = output.getvalue().splitlines()
        assert lines[0].removeprefix("first<<") != lines[3].removeprefix("second<<")
