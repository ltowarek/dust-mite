"""Push an AFK update-branch run's merge and comment it on the PR."""

import json
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from afk.agent import already_covered, read_agent_error, refuse_protected_merge
from afk.effects import Comment, EditLabels, Effect, PushBranch
from afk.git import head_contains, run_git
from afk.github import PullRequest
from afk.labels import needs_car
from afk.runner import Runner
from afk.update_branch_merge import Merge
from afk.writer import Writer


@dataclass(frozen=True)
class Merged:
    """How the run merged `main` into the PR's head, and the run's URL."""

    main: str
    merge: Merge
    run_url: str


def _comment(output: Mapping[str, Any], merged: Merged) -> str:
    main = f"`main` ({merged.main})"
    match merged.merge:
        case Merge.UP_TO_DATE:
            text = f"The branch already contains {main}; this AFK run pushed nothing."
        case Merge.CLEAN:
            text = f"Merged {main} into the branch with no conflicts."
        case Merge.CONFLICT:
            return (
                f"> *Conflicts with {main} resolved by an AFK agent session.* "
                f"([run]({merged.run_url}))\n\n{output['conflict_summary']}\n"
                f"{already_covered(output)}"
            )
    return f"{text}\n\n**Run:** {merged.run_url}\n"


def plan(
    output: Mapping[str, Any], pr: PullRequest, merged: Merged, *, repository: str
) -> list[Effect]:
    """Return the writes that push the merge and comment it on the PR."""
    push = PushBranch(repository=repository, branch=pr.branch, lease=pr.head_sha)
    car = EditLabels(number=pr.number, add=(needs_car(output.get("car_variant", "")),))
    return [
        *([push] if merged.merge != Merge.UP_TO_DATE else []),
        Comment(number=pr.number, body=_comment(output, merged)),
        *([car] if output.get("needs_dut_run") else []),
    ]


def unfinished(*, dirty: bool, merging: bool, contains: bool) -> str | None:
    """Return why the agent's merge is unfinished, or None when it is committed."""
    if dirty:
        return "The working tree has uncommitted changes."
    if merging:
        return "The merge is not committed."
    if not contains:
        return "HEAD does not contain both the branch and main."
    return None


def _merging(git: Runner, env: Mapping[str, str]) -> bool:
    try:
        run_git(git, env, ["rev-parse", "-q", "--verify", "MERGE_HEAD"])
    except subprocess.CalledProcessError:
        return False
    return True


def _refuse_unfinished(
    git: Runner, env: Mapping[str, str], head: str, main: str
) -> None:
    error = unfinished(
        dirty=bool(run_git(git, env, ["status", "--porcelain"]).strip()),
        merging=_merging(git, env),
        contains=head_contains(git, env, head) and head_contains(git, env, main),
    )
    if error:
        raise SystemExit(error)


def run(git: Runner, env: Mapping[str, str], writer: Writer) -> None:
    """Check the agent's merge after conflicts, then push it and comment it."""
    pr = PullRequest(
        number=int(env["AFK_PR"]),
        branch=env["AFK_BRANCH"],
        head_sha=env["AFK_HEAD_SHA"],
    )
    repository = env["GH_REPO"]
    merged = Merged(
        main=env["AFK_MAIN_SHA"],
        merge=Merge(env["AFK_MERGE"]),
        run_url=f"{env['GITHUB_SERVER_URL']}/{repository}/actions/runs/"
        f"{env['GITHUB_RUN_ID']}",
    )
    output: Mapping[str, Any] = {}
    if merged.merge == Merge.CONFLICT:
        if env["AFK_AGENT_OUTCOME"] != "success":
            writer.set_output("agent-error", read_agent_error(env))
            return
        _refuse_unfinished(git, env, pr.head_sha, merged.main)
        refuse_protected_merge(git, env, pr.head_sha, merged.main)
        output = json.loads(env["AFK_AGENT_OUTPUT"])
    for effect in plan(output, pr, merged, repository=repository):
        writer.write(effect)
