"""Guards the exact command each write runs, and that a dry run runs none."""

import json
from collections.abc import Mapping, Sequence

import pytest

from afk.effects import Comment, DispatchWorkflow, Effect, ReplaceLabel
from afk.writer import Writer

ENV = {
    "AFK_APP_TOKEN": "app-token",
    "AFK_WORKFLOW_TOKEN": "workflow-token",
    "GH_REPO": "owner/repo",
}


class RunnerSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str, str]] = []

    def __call__(self, args: Sequence[str], env: Mapping[str, str]) -> str:
        self.calls.append((list(args), env["GH_TOKEN"], env["GH_REPO"]))
        return ""


EFFECTS: list[Effect] = [
    DispatchWorkflow(workflow="afk-run.yml", inputs={"number": "7"}),
    ReplaceLabel(number=7, remove="afk:queued", add="afk:in-progress"),
    Comment(number=7, body="Promoted."),
]


class TestWriterCall:
    @pytest.mark.parametrize(
        ("effect", "args", "token"),
        [
            (
                DispatchWorkflow(
                    workflow="afk-run.yml", inputs={"number": "7", "comment-id": "555"}
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
            ),
            (
                ReplaceLabel(number=7, remove="afk:queued", add="afk:blocked"),
                [
                    "gh",
                    "issue",
                    "edit",
                    "7",
                    "--remove-label",
                    "afk:queued",
                    "--add-label",
                    "afk:blocked",
                ],
                "app-token",
            ),
            (
                Comment(number=7, body="Hello `there`"),
                ["gh", "issue", "comment", "7", "--body", "Hello `there`"],
                "app-token",
            ),
        ],
    )
    def test_runs_each_write_as_its_gh_command_with_its_token(
        self, effect: Effect, args: list[str], token: str
    ) -> None:
        runner = RunnerSpy()

        Writer(runner, ENV)(effect)

        assert runner.calls == [(args, token, "owner/repo")]

    def test_a_dry_run_runs_no_command(self) -> None:
        runner = RunnerSpy()
        writer = Writer(runner, {**ENV, "AFK_DRY_RUN": "true"})

        for effect in EFFECTS:
            writer(effect)

        assert runner.calls == []


class TestWriterOutputs:
    def test_a_dry_run_reports_its_writes_as_effects(self) -> None:
        writer = Writer(RunnerSpy(), {**ENV, "AFK_DRY_RUN": "true"})

        for effect in EFFECTS:
            writer(effect)

        assert json.loads(writer.outputs()["effects"]) == [
            {
                "type": "DispatchWorkflow",
                "workflow": "afk-run.yml",
                "inputs": {"number": "7"},
            },
            {
                "type": "ReplaceLabel",
                "number": 7,
                "remove": "afk:queued",
                "add": "afk:in-progress",
            },
            {"type": "Comment", "number": 7, "body": "Promoted."},
        ]

    def test_a_dry_run_with_no_writes_reports_no_effects(self) -> None:
        writer = Writer(RunnerSpy(), {**ENV, "AFK_DRY_RUN": "true"})

        assert writer.outputs() == {"effects": "[]"}

    def test_a_real_run_reports_no_effects(self) -> None:
        writer = Writer(RunnerSpy(), ENV)

        writer(Comment(number=7, body="Promoted."))

        assert writer.outputs() == {}
