"""Push an AFK PR run's commits and post its comments from the agent's output."""

import json
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from afk.agent import read_agent_error, read_head, refuse_protected_changes
from afk.effects import (
    Comment,
    CreateReviewComment,
    EditLabels,
    Effect,
    PushBranch,
    ReplyToReviewComment,
)
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


@dataclass(frozen=True)
class Write:
    """A planned write; one with a drop warning may fail without failing the run."""

    effect: Effect
    drop_warning: str | None = None


def _inline_comment(pr: PullRequest, head: str, comment: Mapping[str, Any]) -> Write:
    # GitHub rejects a line outside the PR's diff.
    return Write(
        CreateReviewComment(
            number=pr.number,
            commit=head,
            path=comment["path"],
            line=comment["line"],
            body=comment["body"],
        ),
        drop_warning=f"Dropped the inline comment on {comment['path']}:"
        f"{comment['line']}",
    )


def plan(
    output: Mapping[str, Any], pr: PullRequest, commits: int, head: str
) -> list[Write]:
    """Return the writes that push the agent's commits and post its comments."""
    push = Write(PushBranch(repository=pr.repository, branch=pr.branch, lease=pr.lease))
    car = Write(
        EditLabels(
            number=pr.number, add=(f"needs-car:{output.get('car_variant', '')}",)
        )
    )
    return [
        *([push] if commits else []),
        *(
            Write(
                ReplyToReviewComment(
                    number=pr.number, comment_id=reply["comment_id"], body=reply["body"]
                )
            )
            for reply in output["thread_replies"]
        ),
        *(_inline_comment(pr, head, c) for c in output["inline_comments"]),
        *(
            Write(Comment(number=pr.number, body=body))
            for body in output["top_level_comments"]
        ),
        *([car] if commits and output["needs_dut_run"] else []),
    ]


def _write(writer: Writer, write: Write) -> None:
    try:
        writer.write(write.effect)
    except subprocess.CalledProcessError:
        if write.drop_warning is None:
            raise
        sys.stdout.write(f"::warning::{write.drop_warning}\n")


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
    head = read_head(git, env)
    for write in plan(output, pr, commits, head):
        _write(writer, write)
