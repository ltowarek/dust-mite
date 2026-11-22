"""Push an AFK PR run's commits and post its comments from the agent's output."""

import json
from collections.abc import Mapping
from typing import Any

from afk.agent import read_agent_error, refuse_protected_changes
from afk.effects import (
    Comment,
    CreateReviewComment,
    EditLabels,
    Effect,
    PushBranch,
    ReplyToReviewComment,
)
from afk.git import read_commit_count, read_head
from afk.github import PullRequest
from afk.labels import needs_car
from afk.runner import Runner
from afk.writer import Writer


def acted(output: Mapping[str, Any], commits: int) -> bool:
    """Whether the agent committed, or left a reply or comment to post."""
    comments = ("thread_replies", "inline_comments", "top_level_comments")
    return bool(commits) or any(output[key] for key in comments)


def plan(
    output: Mapping[str, Any],
    pr: PullRequest,
    *,
    repository: str,
    commits: int,
    head: str,
) -> list[Effect]:
    """Return the writes that push the agent's commits and post its comments."""
    push = PushBranch(repository=repository, branch=pr.branch, lease=pr.head_sha)
    car = EditLabels(number=pr.number, add=(needs_car(output.get("car_variant", "")),))
    return [
        *([push] if commits else []),
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
                path=c["path"],
                line=c["line"],
                body=c["body"],
            )
            for c in output["inline_comments"]
        ),
        *(
            Comment(number=pr.number, body=body)
            for body in output["top_level_comments"]
        ),
        *([car] if commits and output["needs_dut_run"] else []),
    ]


def run(git: Runner, env: Mapping[str, str], writer: Writer) -> None:
    """Refuse protected changes, then push the commits and post the comments."""
    if env["AFK_AGENT_OUTCOME"] != "success":
        writer.set_output("agent-error", read_agent_error(env))
        return
    pr = PullRequest(
        number=int(env["AFK_PR"]),
        branch=env["AFK_BRANCH"],
        head_sha=env["AFK_HEAD_SHA"],
    )
    refuse_protected_changes(git, env, pr.head_sha)
    output = json.loads(env["AFK_AGENT_OUTPUT"])
    commits = read_commit_count(git, env, pr.head_sha)
    if not acted(output, commits):
        msg = "Refused to publish: the agent neither committed nor commented."
        raise SystemExit(msg)
    head = read_head(git, env)
    for effect in plan(
        output, pr, repository=env["GH_REPO"], commits=commits, head=head
    ):
        writer.write(effect)
