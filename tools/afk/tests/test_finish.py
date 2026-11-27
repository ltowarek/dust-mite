"""Guards the writes that end an AFK run, and the release after a failed one."""

import functools
import json
import subprocess
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from afk import finish
from afk.effects import (
    CloseIssue,
    Comment,
    CommentPullRequest,
    CreateIssue,
    DispatchWorkflow,
    EditLabels,
    Effect,
    React,
)
from afk.finish import (
    FailedStep,
    Needs,
    Run,
    Workflow,
    failed_step,
    job_errors,
    plan,
    plan_failure,
)
from afk.writer import Writer
from tests.test_doubles import GhCall, GhSpy, GitSpy, read_outputs

# Joins a job and its step in a failure reason.
SEP = " \N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK} "
RUN_URL = "https://github.com/owner/repo/actions/runs/99"
RUN = Run(workflow=Workflow.AFK_RUN, number=12, comment_id=None, url=RUN_URL)
BRANCH = "afk/issue-12-99"
SPEC_RUN = {"spec": "true", "child-ticket": "14"}
DONE = {
    "outcome": "done",
    "pr-url": "https://github.com/owner/repo/pull/40",
    "sha": "abc123",
}
BLOCK = EditLabels(number=12, add=("afk:blocked",))
UNBLOCK = EditLabels(number=12, remove=("afk:blocked",))
RELEASE = EditLabels(number=12, remove=("afk:in-progress",))
PR_RUN = Run(workflow=Workflow.AFK_RUN_PR, number=12, comment_id=555, url=RUN_URL)
UPDATE_RUN = replace(PR_RUN, workflow=Workflow.AFK_UPDATE_BRANCH)


def needs_context(
    check: dict[str, str] | None = None,
    implement: dict[str, str] | None = None,
    check_result: str = "success",
    implement_result: str = "success",
) -> dict[str, Any]:
    return {
        "check": {"result": check_result, "outputs": check or {}},
        "implement": {"result": implement_result, "outputs": implement or {}},
    }


def needs(
    check: dict[str, str] | None = None,
    implement: dict[str, str] | None = None,
    check_result: str = "success",
    implement_result: str = "success",
) -> Needs:
    return Needs.parse(
        needs_context(check, implement, check_result, implement_result),
        Workflow.AFK_RUN,
    )


def failure_report(text: str, reason: str, command: str = "/afk implement") -> Comment:
    return Comment(
        number=12,
        body=f"{text}.\n\n**Reason:** {reason}\n\n**Run:** {RUN_URL}\n\n"
        f"Comment `{command}` to retry.\n",
    )


class TestPlan:
    @pytest.mark.parametrize(
        ("run", "reaction"),
        [
            pytest.param(RUN, [], id="on a ticket"),
            pytest.param(
                PR_RUN,
                [React(comment_id=555, content="confused")],
                id="on a PR, reacting confused",
            ),
            pytest.param(
                UPDATE_RUN,
                [React(comment_id=555, content="confused")],
                id="on a branch update, reacting confused",
            ),
        ],
    )
    def test_refuses_with_the_check_jobs_reason_then_releases(
        self, run: Run, reaction: list[Effect]
    ) -> None:
        refused = needs(check={"refusal": "Refused."}, implement_result="skipped")

        assert plan(run, refused, None) == [
            Comment(number=12, body="Refused."),
            RELEASE,
            *reaction,
        ]

    def test_labels_a_blocked_refusal_afk_blocked_before_commenting(self) -> None:
        refused = needs(
            check={"refusal": "Refused.", "block": "true"}, implement_result="skipped"
        )

        assert plan(RUN, refused, None)[:2] == [
            BLOCK,
            Comment(number=12, body="Refused."),
        ]

    @pytest.mark.parametrize(
        ("run", "reaction"),
        [
            pytest.param(RUN, [], id="on a ticket"),
            pytest.param(
                PR_RUN,
                [React(comment_id=555, content="rocket")],
                id="on a PR, reacting rocket",
            ),
            pytest.param(
                UPDATE_RUN,
                [React(comment_id=555, content="rocket")],
                id="on a branch update, reacting rocket",
            ),
        ],
    )
    def test_clears_afk_blocked_then_releases_after_its_work(
        self, run: Run, reaction: list[Effect]
    ) -> None:
        assert plan(run, needs(implement=DONE), None) == [
            UNBLOCK,
            RELEASE,
            *reaction,
        ]

    @pytest.mark.parametrize(
        ("finished", "content"),
        [
            pytest.param(needs(implement=DONE), "rocket", id="rocket when done"),
            pytest.param(
                needs(check={"refusal": "Refused."}, implement_result="skipped"),
                "confused",
                id="confused when refused",
            ),
            pytest.param(
                needs(implement={"outcome": "spec_gap"}),
                "confused",
                id="confused at a spec gap",
            ),
            pytest.param(
                needs(implement={"outcome": "needs_car"}),
                "confused",
                id="confused when the fix needs the car",
            ),
            pytest.param(
                needs(implement_result="failure"),
                "confused",
                id="confused when the implement job failed",
            ),
        ],
    )
    def test_reacts_to_the_afk_command_last(
        self, finished: Needs, content: str
    ) -> None:
        effects = plan(replace(RUN, comment_id=555), finished, None)

        assert effects[-1] == React(comment_id=555, content=content)

    def test_does_not_react_without_an_afk_command(self) -> None:
        effects = plan(RUN, needs(implement=DONE), None)

        assert not any(isinstance(effect, React) for effect in effects)

    @pytest.mark.parametrize(
        ("check", "worked"),
        [
            pytest.param({}, 12, id="on the ticket"),
            pytest.param(SPEC_RUN, 14, id="on a spec's child ticket"),
        ],
    )
    def test_files_each_follow_up_ticket_from_the_worked_ticket(
        self, check: dict[str, str], worked: int
    ) -> None:
        output = {
            "outcome": "spec_gap",
            "follow_ups": [
                {
                    "title": "Fix the camera",
                    "type": "bug",
                    "components": ["camera", "web"],
                    "body": "It breaks.",
                },
                {
                    "title": "Document the drive",
                    "type": "documentation",
                    "components": ["drive"],
                    "body": "It is undocumented.",
                },
            ],
        }
        implement = {"outcome": "spec_gap", "agent-output": json.dumps(output)}

        effects = plan(RUN, needs(check=check, implement=implement), None)

        header = (
            f"> *Follow-up ticket filed by an AFK agent session while working "
            f"#{worked}.* ([run]({RUN_URL}))\n\n"
        )
        assert effects[:2] == [
            CreateIssue(
                title="Fix the camera",
                body=f"{header}It breaks.\n",
                labels=("needs-triage", "source:follow-up", "bug", "camera", "web"),
            ),
            CreateIssue(
                title="Document the drive",
                body=f"{header}It is undocumented.\n",
                labels=("needs-triage", "source:follow-up", "documentation", "drive"),
            ),
        ]

    @pytest.mark.parametrize(
        ("run", "comment"),
        [
            pytest.param(
                RUN,
                functools.partial(CommentPullRequest, branch=BRANCH),
                id="on a ticket, on its branch's PR",
            ),
            pytest.param(PR_RUN, functools.partial(Comment, number=12), id="on the PR"),
        ],
    )
    def test_comments_the_follow_ups_already_covered(
        self, run: Run, comment: Callable[..., Effect]
    ) -> None:
        output = {
            "outcome": "done",
            "already_covered": [
                {"problem": "The camera\n   breaks.", "covered_by": 30},
                {"problem": "The drive stalls.", "covered_by": 31},
            ],
        }
        finished = needs(
            check={"branch": BRANCH},
            implement={**DONE, "agent-output": json.dumps(output)},
        )

        assert plan(run, finished, None)[0] == comment(
            body="## Follow-ups already covered\n\n"
            "- The camera breaks. Covered by #30.\n"
            "- The drive stalls. Covered by #31.\n",
        )

    def test_leaves_a_branch_update_s_follow_ups_already_covered_to_its_merge(
        self,
    ) -> None:
        output = {"already_covered": [{"problem": "X.", "covered_by": 30}]}
        finished = needs(implement={"agent-output": json.dumps(output)})

        assert plan(UPDATE_RUN, finished, None) == [
            UNBLOCK,
            RELEASE,
            React(comment_id=555, content="rocket"),
        ]

    @pytest.mark.parametrize(
        "implement",
        [
            pytest.param(
                {**DONE, "agent-output": json.dumps({"outcome": "done"})},
                id="without follow-ups already covered",
            ),
            pytest.param(
                {
                    "outcome": "spec_gap",
                    "agent-output": json.dumps(
                        {
                            "outcome": "spec_gap",
                            "already_covered": [{"problem": "X.", "covered_by": 30}],
                        }
                    ),
                },
                id="without a PR",
            ),
        ],
    )
    def test_comments_nothing_on_a_pr(self, implement: dict[str, str]) -> None:
        effects = plan(RUN, needs(implement=implement), None)

        assert not any(isinstance(e, CommentPullRequest) for e in effects)

    def test_closes_the_spec_s_child_ticket_with_the_pushed_commit(self) -> None:
        finished = needs(check={**SPEC_RUN, "last-run": "true"}, implement=DONE)

        assert plan(RUN, finished, None)[0] == CloseIssue(
            number=14, comment="Implemented in abc123"
        )

    @pytest.mark.parametrize(
        ("implement", "reason"),
        [
            pytest.param(
                {"outcome": "spec_gap"},
                "It has a spec gap, whose questions are on it.",
                id="at a spec gap",
            ),
            pytest.param(
                {"outcome": "needs_car", "needs-car-reason": "Only the car shows it."},
                "Finding the fix needs the car: Only the car shows it.",
                id="when the fix needs the car",
            ),
        ],
    )
    def test_stops_the_spec_s_implementation(
        self, implement: dict[str, str], reason: str
    ) -> None:
        effects = plan(RUN, needs(check=SPEC_RUN, implement=implement), None)

        assert effects[1:3] == [
            BLOCK,
            Comment(
                number=12,
                body="AFK spec implementation stopped at child ticket #14.\n\n"
                f"**Reason:** {reason}\n\n"
                f"**Run:** {RUN_URL}\n\n"
                "Comment `/afk implement` to resume it.\n",
            ),
        ]

    @pytest.mark.parametrize(
        ("run", "failed", "step", "effects"),
        [
            pytest.param(
                RUN,
                needs(implement_result="failure"),
                FailedStep(f"implement{SEP}Run the AFK agent session"),
                [
                    BLOCK,
                    failure_report(
                        "The AFK run failed",
                        f"`implement{SEP}Run the AFK agent session` failed.",
                    ),
                    RELEASE,
                ],
                id="names the failed step",
            ),
            pytest.param(
                RUN,
                needs(
                    implement={"agent-error": "Out of turns."},
                    implement_result="failure",
                ),
                FailedStep(f"implement{SEP}Run the AFK agent session"),
                [
                    BLOCK,
                    failure_report(
                        "The AFK run failed",
                        f"`implement{SEP}Run the AFK agent session` failed. "
                        "The agent reported: Out of turns.",
                    ),
                    RELEASE,
                ],
                id="adds the agent's error",
            ),
            pytest.param(
                RUN,
                needs(implement_result="failure"),
                FailedStep(
                    f"implement{SEP}Run the AFK agent session",
                    errors=("Action failed.\n\nAdd the bot.", "Disk full."),
                ),
                [
                    BLOCK,
                    failure_report(
                        "The AFK run failed",
                        f"`implement{SEP}Run the AFK agent session` failed. "
                        "Its job reported:\n\n> Action failed.\n>\n> Add the bot."
                        "\n\n> Disk full.",
                    ),
                    RELEASE,
                ],
                id="quotes each error that its job reported",
            ),
            pytest.param(
                RUN,
                needs(
                    implement={"agent-error": "Out of turns."},
                    implement_result="failure",
                ),
                FailedStep(
                    f"implement{SEP}Run the AFK agent session",
                    errors=("Out of turns.",),
                ),
                [
                    BLOCK,
                    failure_report(
                        "The AFK run failed",
                        f"`implement{SEP}Run the AFK agent session` failed. "
                        "The agent reported: Out of turns.",
                    ),
                    RELEASE,
                ],
                id="leaves out a job error that repeats the agent's error",
            ),
            pytest.param(
                RUN,
                needs(implement_result="failure"),
                None,
                [
                    BLOCK,
                    failure_report("The AFK run failed", "`unknown step` failed."),
                    RELEASE,
                ],
                id="names an unknown step when no step failed",
            ),
            pytest.param(
                RUN,
                needs(check=SPEC_RUN, implement_result="failure"),
                FailedStep(f"implement{SEP}Run the AFK agent session"),
                [
                    BLOCK,
                    failure_report(
                        "The AFK run failed on child ticket #14",
                        f"`implement{SEP}Run the AFK agent session` failed.",
                    ),
                    RELEASE,
                ],
                id="names the spec's child ticket",
            ),
            pytest.param(
                PR_RUN,
                needs(
                    implement={"agent-error": "Out of turns."},
                    implement_result="failure",
                ),
                FailedStep(f"implement{SEP}Run the agent"),
                [
                    BLOCK,
                    failure_report(
                        "The AFK run on this PR failed",
                        f"`implement{SEP}Run the agent` failed. "
                        "The agent reported: Out of turns.",
                    ),
                    RELEASE,
                    *[React(comment_id=555, content="confused")],
                ],
                id="on a PR, reacting confused",
            ),
            pytest.param(
                UPDATE_RUN,
                needs(implement_result="failure"),
                FailedStep(f"update-branch{SEP}Merge main"),
                [
                    BLOCK,
                    failure_report(
                        "The AFK run that updates this PR's branch failed",
                        f"`update-branch{SEP}Merge main` failed.",
                        "/afk update-branch",
                    ),
                    RELEASE,
                    React(comment_id=555, content="confused"),
                ],
                id="on a branch update, retried by its own command",
            ),
        ],
    )
    def test_reports_a_failed_job_then_releases(
        self, run: Run, failed: Needs, step: FailedStep | None, effects: list[Effect]
    ) -> None:
        assert plan(run, failed, step) == effects

    def test_reports_a_cancelled_check_job(self) -> None:
        cancelled = needs(check_result="cancelled", implement_result="skipped")

        assert plan(RUN, cancelled, FailedStep("check")) == [
            BLOCK,
            failure_report("The AFK run failed", "`check` failed."),
            RELEASE,
        ]

    def test_queues_the_spec_with_the_afk_command_in_a_marker(self) -> None:
        queued = needs(check={"queue": "true"}, implement_result="skipped")

        assert plan(replace(RUN, comment_id=555), queued, None) == [
            EditLabels(number=12, add=("afk:queued",)),
            Comment(
                number=12,
                body="Queued (`afk:queued`) until one of its child tickets is "
                "unblocked. <!-- afk-command: 555 -->",
            ),
            RELEASE,
        ]

    @pytest.mark.parametrize(
        ("comment_id", "inputs"),
        [
            pytest.param(
                555,
                {"number": "12", "comment-id": "555"},
                id="passing on the AFK command",
            ),
            pytest.param(None, {"number": "12"}, id="without an AFK command"),
        ],
    )
    def test_dispatches_the_spec_s_next_run_and_keeps_it_in_progress(
        self, comment_id: int | None, inputs: dict[str, str]
    ) -> None:
        continued = needs(check={**SPEC_RUN, "last-run": "false"}, implement=DONE)

        assert plan(replace(RUN, comment_id=comment_id), continued, None) == [
            CloseIssue(number=14, comment="Implemented in abc123"),
            UNBLOCK,
            DispatchWorkflow(workflow="afk-run.yml", inputs=inputs),
        ]


class TestNeeds:
    class TestParse:
        def test_reads_a_branch_update_s_update_branch_job(self) -> None:
            context = {
                "check": {"result": "success", "outputs": {}},
                "update-branch": {
                    "result": "failure",
                    "outputs": {"agent-error": "Out of turns."},
                },
            }

            parsed = Needs.parse(context, Workflow.AFK_UPDATE_BRANCH)

            assert (parsed.work_result, parsed.agent_error) == (
                "failure",
                "Out of turns.",
            )


class TestPlanFailure:
    def test_reports_the_failed_write_then_releases_the_ticket(self) -> None:
        effects = plan_failure(
            replace(RUN, comment_id=555), needs(implement=DONE), "CloseIssue"
        )

        assert effects == [
            BLOCK,
            failure_report("The AFK run failed", f"`finish{SEP}CloseIssue` failed."),
            RELEASE,
            React(comment_id=555, content="confused"),
        ]

    def test_names_the_spec_s_child_ticket_and_the_agent_s_error(self) -> None:
        failed = needs(check=SPEC_RUN, implement={**DONE, "agent-error": "Oops."})

        assert plan_failure(RUN, failed, "CloseIssue")[1] == failure_report(
            "The AFK run failed on child ticket #14",
            f"`finish{SEP}CloseIssue` failed. The agent reported: Oops.",
        )


def job(
    name: str, conclusion: str | None, *steps: tuple[str, str | None]
) -> dict[str, Any]:
    return {
        "id": 7,
        "name": name,
        "conclusion": conclusion,
        "steps": [{"name": n, "conclusion": c} for n, c in steps],
    }


class TestFailedStep:
    @pytest.mark.parametrize(
        ("jobs", "step"),
        [
            pytest.param(
                [
                    job("check", "success", ("Read", "success")),
                    job(
                        "implement",
                        "failure",
                        ("Checkout", "success"),
                        ("Agent", "failure"),
                    ),
                ],
                FailedStep(f"implement{SEP}Agent", job_id=7),
                id="names the failed job's failed step",
            ),
            pytest.param(
                [
                    job(
                        "implement",
                        "cancelled",
                        ("Checkout", "success"),
                        ("Agent", "cancelled"),
                    )
                ],
                FailedStep(f"implement{SEP}Agent", job_id=7),
                id="names a cancelled job's cancelled step",
            ),
            pytest.param(
                [
                    job("check", "failure", ("Read", "failure")),
                    job("implement", "failure", ("Agent", "failure")),
                ],
                FailedStep(f"check{SEP}Read", job_id=7),
                id="names the first failed job",
            ),
            pytest.param(
                [job("finish", None, ("Mint", "failure"), ("Finish", None))],
                FailedStep(f"finish{SEP}Mint", job_id=7),
                id="names a failed step of a job that is still running",
            ),
            pytest.param(
                [job("implement", "cancelled")],
                FailedStep("implement", job_id=7),
                id="names a cancelled job that ran no step",
            ),
            pytest.param(
                [job("finish", None, ("Mint", "cancelled"), ("Finish", None))],
                None,
                id="skips a running job whose only stopped step was cancelled",
            ),
            pytest.param(
                [{"id": 7, "name": "check", "conclusion": "success", "steps": None}],
                None,
                id="skips a job without steps",
            ),
            pytest.param(
                [job("check", "success", ("Read", "success"))],
                None,
                id="finds none when nothing failed",
            ),
        ],
    )
    def test_finds_the_first_failed_step(
        self, jobs: list[dict[str, Any]], step: FailedStep | None
    ) -> None:
        assert failed_step({"total_count": len(jobs), "jobs": jobs}) == step


def annotation(level: str, message: str) -> dict[str, Any]:
    return {"annotation_level": level, "message": message}


class TestJobErrors:
    @pytest.mark.parametrize(
        ("annotations", "errors"),
        [
            pytest.param(
                [annotation("failure", "Action failed with error: Add the bot.")],
                ("Action failed with error: Add the bot.",),
                id="keeps a failure annotation's message",
            ),
            pytest.param(
                [annotation("failure", "Process completed with exit code 1.")],
                (),
                id="drops the runner's exit code, which names no cause",
            ),
            pytest.param(
                [annotation("warning", "Node 20 is deprecated.")],
                (),
                id="drops a warning",
            ),
        ],
    )
    def test_keeps_the_errors_that_name_a_cause(
        self, annotations: list[dict[str, Any]], errors: tuple[str, ...]
    ) -> None:
        assert job_errors(annotations) == errors


FAILED_STEP_READ = (
    "api",
    "repos/owner/repo/actions/runs/99/attempts/1/jobs?per_page=100",
)
JOB_ERRORS_READ = ("api", "repos/owner/repo/check-runs/7/annotations?per_page=100")
ENV = {
    "AFK_APP_TOKEN": "app-token",
    "AFK_WORKFLOW_TOKEN": "workflow-token",
    "GH_REPO": "owner/repo",
    "GITHUB_SERVER_URL": "https://github.com",
    "GITHUB_RUN_ID": "99",
    "GITHUB_RUN_ATTEMPT": "1",
    "AFK_WORKFLOW": "afk-run",
    "AFK_TICKET": "12",
    "AFK_COMMENT_ID": "",
}


def env_for(finished: dict[str, Any], *, dry_run: bool = False) -> dict[str, str]:
    return {
        **ENV,
        "AFK_NEEDS": json.dumps(finished),
        "AFK_DRY_RUN": "true" if dry_run else "false",
    }


def written(effects: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = json.loads(effects)
    return result


def gh_call(*args: str) -> GhCall:
    return GhCall(list(args), "app-token", "owner/repo")


class TestRun:
    def test_reports_the_plan_in_a_dry_run_and_reads_nothing(
        self, tmp_path: Path
    ) -> None:
        gh, git = GhSpy(), GitSpy()
        env = env_for(needs_context(implement=DONE), dry_run=True)
        output = tmp_path / "output"
        writer = Writer(gh, git, env, output)

        finish.run(gh, env, writer)
        writer.report()

        assert (gh.calls, written(read_outputs(output)["effects"])) == (
            [],
            [
                {
                    "type": "EditLabels",
                    "number": 12,
                    "add": [],
                    "remove": ["afk:blocked"],
                },
                {
                    "type": "EditLabels",
                    "number": 12,
                    "add": [],
                    "remove": ["afk:in-progress"],
                },
            ],
        )

    def test_reads_the_failed_step_and_its_job_s_errors_with_the_workflow_token(
        self, tmp_path: Path
    ) -> None:
        response = {"jobs": [job("implement", "failure", ("Agent", "failure"))]}
        annotations = [
            annotation("failure", "Add the bot."),
            annotation("failure", "Process completed with exit code 1."),
        ]
        gh = GhSpy(
            {
                FAILED_STEP_READ: json.dumps(response),
                JOB_ERRORS_READ: json.dumps(annotations),
            }
        )
        git = GitSpy()
        env = env_for(needs_context(implement_result="failure"), dry_run=True)
        output = tmp_path / "output"
        writer = Writer(gh, git, env, output)

        finish.run(gh, env, writer)
        writer.report()

        assert (gh.calls, written(read_outputs(output)["effects"])[1]["body"]) == (
            [
                GhCall(list(FAILED_STEP_READ), "workflow-token", "owner/repo"),
                GhCall(list(JOB_ERRORS_READ), "workflow-token", "owner/repo"),
            ],
            failure_report(
                "The AFK run failed",
                f"`implement{SEP}Agent` failed. Its job reported:\n\n> Add the bot.",
            ).body,
        )

    def test_reports_and_releases_after_a_failed_write_then_fails(
        self, tmp_path: Path
    ) -> None:
        close = ("issue", "close", "14", "--comment", "Implemented in abc123")
        gh, git = GhSpy(failing=close), GitSpy()
        env = env_for(
            needs_context(check={**SPEC_RUN, "last-run": "true"}, implement=DONE)
        )

        with pytest.raises(subprocess.CalledProcessError):
            finish.run(gh, env, Writer(gh, git, env, tmp_path / "output"))

        assert gh.calls == [
            gh_call(*close),
            gh_call("issue", "edit", "12", "--add-label", "afk:blocked"),
            gh_call(
                "issue",
                "comment",
                "12",
                "--body",
                failure_report(
                    "The AFK run failed on child ticket #14",
                    f"`finish{SEP}CloseIssue` failed.",
                ).body,
            ),
            gh_call("issue", "edit", "12", "--remove-label", "afk:in-progress"),
        ]

    def test_reports_and_releases_after_a_failed_read_then_fails(
        self, tmp_path: Path
    ) -> None:
        gh, git = GhSpy(failing=("api",)), GitSpy()
        env = env_for(needs_context(implement_result="failure"))

        with pytest.raises(subprocess.CalledProcessError):
            finish.run(gh, env, Writer(gh, git, env, tmp_path / "output"))

        assert gh.calls[2] == gh_call(
            "issue",
            "comment",
            "12",
            "--body",
            failure_report(
                "The AFK run failed", f"`finish{SEP}Read the failed step` failed."
            ).body,
        )
