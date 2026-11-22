"""Decide whether an AFK run on a PR refuses or proceeds, and read its conversation."""

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from afk.effects import EditLabels
from afk.labels import Label
from afk.writer import Runner, Token, Writer, run_gh

_REVIEW_THREADS_QUERY = """
query($owner: String!, $repo: String!, $number: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequest(number: $number) {
      reviewThreads(first: 100) {
        nodes {
          isResolved
          comments(first: 100) {
            nodes { databaseId path line originalLine body author { login } }
          }
        }
      }
    }
  }
}
"""


@dataclass(frozen=True)
class PullRequest:
    """A pull request on the tracker."""

    url: str
    open: bool
    fork: bool
    branch: str
    head_sha: str


@dataclass(frozen=True)
class Conversation:
    """The PR's unresolved conversation that the agent acts on."""

    issue_comments: tuple[dict[str, Any], ...] = ()
    review_summaries: tuple[dict[str, Any], ...] = ()
    review_threads: tuple[dict[str, Any], ...] = ()


def _login(author: Mapping[str, Any] | None) -> str | None:
    # GitHub returns no author for a deleted account.
    return None if author is None else author["login"]


def _message(comment: Mapping[str, Any]) -> dict[str, Any]:
    return {"author": _login(comment["author"]), "body": comment["body"]}


def pull_request(view: Mapping[str, Any]) -> PullRequest:
    """Return a pull request from `gh pr view`."""
    return PullRequest(
        url=view["url"],
        open=view["state"] == "OPEN",
        fork=view["isCrossRepository"],
        branch=view["headRefName"],
        head_sha=view["headRefOid"],
    )


def _thread(comments: list[dict[str, Any]]) -> dict[str, Any]:
    # A reply goes to a thread's first comment; the REST API rejects replies to replies.
    first = comments[0]
    return {
        "comment_id": first["databaseId"],
        "path": first["path"],
        "line": first["line"] or first["originalLine"],
        "comments": [_message(c) for c in comments],
    }


def conversation(view: Mapping[str, Any], threads: Mapping[str, Any]) -> Conversation:
    """Return the unresolved conversation from `gh pr view` and the threads query."""
    nodes = threads["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
    return Conversation(
        # AFK commands are requests for this run, not feedback to act on.
        issue_comments=tuple(
            _message(c) for c in view["comments"] if not c["body"].startswith("/afk")
        ),
        review_summaries=tuple(
            {"author": _login(r["author"]), "state": r["state"], "body": r["body"]}
            for r in view["reviews"]
            if r["body"]
        ),
        review_threads=tuple(
            _thread(n["comments"]["nodes"]) for n in nodes if not n["isResolved"]
        ),
    )


@dataclass(frozen=True)
class CheckResult:
    """Whether an AFK run on a PR is refused, or what it works on."""

    refusal: str | None = None
    url: str | None = None
    branch: str | None = None
    head_sha: str | None = None
    conversation: Conversation | None = None


def outputs(result: CheckResult) -> dict[str, str]:
    """Return the check job's step outputs; an unset field sets none."""
    conversation = result.conversation
    values = {
        "refusal": result.refusal,
        "url": result.url,
        "branch": result.branch,
        "head-sha": result.head_sha,
        "conversation": None
        if conversation is None
        else json.dumps(asdict(conversation)),
    }
    return {name: value for name, value in values.items() if value is not None}


def check(pr: PullRequest, conversation: Conversation, head_sha: str) -> CheckResult:
    """Decide whether the run goes ahead; it works on `head_sha`, or the PR's head."""
    if not pr.open:
        return CheckResult(refusal="Refused to run: this PR is not open.")
    if pr.fork:
        return CheckResult(
            refusal="Refused to run: this PR's branch is in a fork, and an AFK run "
            "never runs a fork's code with the repository's secrets."
        )
    if not any(asdict(conversation).values()):
        return CheckResult(
            refusal="Refused to run: this PR has no unresolved review threads, "
            "review summaries or top-level comments to act on."
        )
    return CheckResult(
        url=pr.url,
        branch=pr.branch,
        head_sha=head_sha or pr.head_sha,
        conversation=conversation,
    )


def _read(gh: Runner, env: Mapping[str, str], *args: str) -> str:
    return run_gh(gh, env, Token.WORKFLOW, args)


def run(gh: Runner, env: Mapping[str, str], writer: Writer) -> None:
    """Mark the PR in progress, then decide whether its AFK run goes ahead."""
    number = env["AFK_PR"]
    writer.write(EditLabels(number=int(number), add=(Label.IN_PROGRESS,)))
    fields_ = "state,url,isCrossRepository,headRefName,headRefOid,comments,reviews"
    view = json.loads(_read(gh, env, "pr", "view", number, "--json", fields_))
    owner, repo = env["GH_REPO"].split("/")
    threads = _read(
        gh,
        env,
        "api",
        "graphql",
        "-f",
        f"query={_REVIEW_THREADS_QUERY}",
        "-f",
        f"owner={owner}",
        "-f",
        f"repo={repo}",
        "-F",
        f"number={number}",
    )
    result = check(
        pull_request(view),
        conversation(view, json.loads(threads)),
        env.get("AFK_HEAD_SHA", ""),
    )
    for name, value in outputs(result).items():
        writer.set_output(name, value)
