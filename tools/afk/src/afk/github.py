"""Run `gh` with a token, the GitHub types and reads phases share, and `gh` writes."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, assert_never

from afk.effects import (
    CloseIssue,
    Comment,
    CommentPullRequest,
    CreateIssue,
    CreatePullRequest,
    CreateReviewComment,
    EditLabels,
    EditPullRequest,
    EditPullRequestLabels,
    IssueWrite,
    MarkPullRequestReady,
    PullRequestWrite,
    React,
    ReplyToReviewComment,
    ReviewWrite,
)
from afk.runner import Runner


class Token(StrEnum):
    """The environment variable that holds a command's token."""

    APP = "AFK_APP_TOKEN"
    WORKFLOW = "AFK_WORKFLOW_TOKEN"


def run_gh(
    gh: Runner, env: Mapping[str, str], token: Token, args: Sequence[str]
) -> str:
    """Run a gh command with `token` as its GH_TOKEN."""
    return gh(args, {**env, "GH_TOKEN": env[token]})


@dataclass(frozen=True)
class PullRequest:
    """A pull request's number and branch, and the head that a run on it starts from."""

    number: int
    branch: str
    head_sha: str


def read_graphql(
    gh: Runner, env: Mapping[str, str], query: str, number: int | str
) -> dict[str, Any]:
    """Run `query` on the repository and `number`, with the workflow token."""
    owner, repo = env["GH_REPO"].split("/")
    args = [
        "api",
        "graphql",
        "-f",
        f"query={query}",
        "-f",
        f"owner={owner}",
        "-f",
        f"repo={repo}",
        "-F",
        f"number={number}",
    ]
    response: dict[str, Any] = json.loads(run_gh(gh, env, Token.WORKFLOW, args))
    return response


def dispatch_args(workflow: str, inputs: Mapping[str, str]) -> list[str]:
    """Return the `gh` arguments that dispatch `workflow` with `inputs`."""
    fields = [arg for key, value in inputs.items() for arg in ("-f", f"{key}={value}")]
    return ["workflow", "run", workflow, *fields]


def issue_args(effect: IssueWrite) -> list[str]:
    """Return the `gh` arguments of an issue write."""
    args: list[str]
    match effect:
        case EditLabels(number=number, add=add, remove=remove):
            args = ["issue", "edit", str(number), *_label_flags(add, remove)]
        case Comment(number=number, body=body):
            args = ["issue", "comment", str(number), "--body", body]
        case React(comment_id=comment_id, content=content):
            # gh has no reaction subcommand; gh api takes {owner}/{repo} from GH_REPO.
            endpoint = (
                f"repos/{{owner}}/{{repo}}/issues/comments/{comment_id}/reactions"
            )
            args = ["api", "--method", "POST", endpoint, "-f", f"content={content}"]
        case CreateIssue(title=title, body=body, labels=labels):
            flags = [arg for label in labels for arg in ("--label", label)]
            args = ["issue", "create", "--title", title, "--body", body, *flags]
        case CloseIssue(number=number, comment=comment):
            args = ["issue", "close", str(number), "--comment", comment]
        case _:
            assert_never(effect)
    return args


def pull_request_args(effect: PullRequestWrite) -> list[str]:
    """Return the `gh` arguments of a pull request write."""
    args: list[str]
    match effect:
        case CreatePullRequest(branch=branch, title=title, body=body):
            pr = ["--base", "main", "--head", branch, "--title", title, "--body", body]
            args = ["pr", "create", "--draft", *pr]
        case EditPullRequest(branch=branch, title=title, body=body):
            args = ["pr", "edit", branch, "--title", title, "--body", body]
        case EditPullRequestLabels(branch=branch, add=add, remove=remove):
            args = ["pr", "edit", branch, *_label_flags(add, remove)]
        case MarkPullRequestReady(branch=branch):
            args = ["pr", "ready", branch]
        case CommentPullRequest(branch=branch, body=body):
            args = ["pr", "comment", branch, "--body", body]
        case _:
            assert_never(effect)
    return args


def review_args(effect: ReviewWrite) -> list[str]:
    """Return the `gh api` arguments of a review comment write."""
    # gh has no review comment subcommand; gh api takes {owner}/{repo} from GH_REPO.
    comments = f"repos/{{owner}}/{{repo}}/pulls/{effect.number}/comments"
    fields: list[str]
    match effect:
        case ReplyToReviewComment(comment_id=comment_id, body=body):
            endpoint = f"{comments}/{comment_id}/replies"
            fields = ["-f", f"body={body}"]
        case CreateReviewComment(commit=commit, path=path, line=line, body=body):
            endpoint = comments
            # -F sends the line as a number.
            fields = [
                "-f",
                f"body={body}",
                "-f",
                f"commit_id={commit}",
                "-f",
                f"path={path}",
                "-F",
                f"line={line}",
                "-f",
                "side=RIGHT",
            ]
        case _:
            assert_never(effect)
    return ["api", "--method", "POST", endpoint, *fields]


def _label_flags(add: Sequence[str], remove: Sequence[str]) -> list[str]:
    return [
        *(arg for label in add for arg in ("--add-label", label)),
        *(arg for label in remove for arg in ("--remove-label", label)),
    ]
