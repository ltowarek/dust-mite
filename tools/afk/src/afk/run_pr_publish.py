"""Push an AFK PR run's commits and post its comments from the agent's output."""

import json
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from afk.effects import (
    Comment,
    CreateReviewComment,
    EditLabels,
    Effect,
    PushBranch,
    ReplyToReviewComment,
)
from afk.publish import read_agent_error, refuse_protected_changes
from afk.writer import Runner, Writer, run_git


@dataclass(frozen=True)
class PullRequest:
    """The PR that the run works on; the agent started from its head `lease`."""

    repository: str
    number: int
    branch: str
    lease: str


def acted(output: Mapping[str, Any], commits: int) -> bool:
    """Whether the agent committed, or left a reply or comment to post."""
    comments = ("thread_replies", "inline_comments", "top_level_comments")
    return bool(commits) or any(output[key] for key in comments)


def plan(
    output: Mapping[str, Any], pr: PullRequest, commits: int, head: str
) -> list[Effect]:
    """Return the writes that push the agent's commits and post its comments."""
    push: list[Effect] = [
        PushBranch(repository=pr.repository, branch=pr.branch, lease=pr.lease)
    ]
    car: list[Effect] = [
        EditLabels(
            number=pr.number, add=(f"needs-car:{output.get('car_variant', '')}",)
        )
    ]
    return [
        *(push if commits else []),
        *(
            ReplyToReviewComment(
                number=pr.number, comment_id=reply["comment_id"], body=reply["body"]
            )
            for reply in output["thread_replies"]
        ),
        *(
            CreateReviewComment(
                number=pr.number,
                commit=head,
                path=comment["path"],
                line=comment["line"],
                body=comment["body"],
            )
            for comment in output["inline_comments"]
        ),
        *(
            Comment(number=pr.number, body=body)
            for body in output["top_level_comments"]
        ),
        *(car if commits and output["needs_dut_run"] else []),
    ]


def _write(writer: Writer, effect: Effect) -> None:
    try:
        writer.write(effect)
    except subprocess.CalledProcessError:
        if not isinstance(effect, CreateReviewComment):
            raise
        # GitHub rejects a line outside the PR's diff.
        sys.stdout.write(
            f"::warning::Dropped the inline comment on {effect.path}:{effect.line}\n"
        )


def run(git: Runner, env: Mapping[str, str], writer: Writer) -> None:
    """Refuse protected changes, then push the commits and post the comments."""
    if env["AFK_AGENT_OUTCOME"] != "success":
        writer.set_output("agent-error", read_agent_error(env))
        return
    pr = PullRequest(
        repository=env["GH_REPO"],
        number=int(env["AFK_PR"]),
        branch=env["AFK_BRANCH"],
        lease=env["AFK_HEAD_SHA"],
    )
    refuse_protected_changes(git, env, pr.lease)
    output = json.loads(env["AFK_AGENT_OUTPUT"])
    commits = int(run_git(git, env, None, ["rev-list", "--count", f"{pr.lease}..HEAD"]))
    if not acted(output, commits):
        msg = "Refused to publish: the agent neither committed nor commented."
        raise SystemExit(msg)
    head = run_git(git, env, None, ["rev-parse", "HEAD"]).strip()
    for effect in plan(output, pr, commits, head):
        _write(writer, effect)
