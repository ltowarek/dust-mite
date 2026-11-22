"""GitHub types and reads that several phases share."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from afk.writer import Runner, Token, run_gh


@dataclass(frozen=True)
class PullRequest:
    """A pull request's number and branch, and the head that a run on it starts from."""

    number: int
    branch: str
    head_sha: str


def read_graphql(
    gh: Runner, env: Mapping[str, str], query: str, number: int | str
) -> dict[str, Any]:
    """Run `query` with the repository's owner, name and `number`, as the workflow."""
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
