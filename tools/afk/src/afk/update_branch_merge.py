"""Merge `main` into the PR's head for an AFK update-branch run."""

import subprocess
from collections.abc import Mapping
from enum import StrEnum

from afk.git import run_git
from afk.runner import Runner
from afk.writer import Writer

_MAIN = "origin/main"


class Merge(StrEnum):
    """How merging `main` into the PR's head went."""

    UP_TO_DATE = "up-to-date"
    CLEAN = "clean"
    CONFLICT = "conflict"


def _merge(git: Runner, env: Mapping[str, str]) -> Merge:
    if run_git(git, env, ["rev-list", "--count", f"HEAD..{_MAIN}"]).strip() == "0":
        return Merge.UP_TO_DATE
    try:
        run_git(git, env, ["merge", "--no-edit", _MAIN])
    except subprocess.CalledProcessError:
        if not run_git(git, env, ["diff", "--name-only", "--diff-filter=U"]).strip():
            raise
        return Merge.CONFLICT
    return Merge.CLEAN


def run(git: Runner, env: Mapping[str, str], writer: Writer) -> None:
    """Merge `main` as the App's bot, leaving any conflicts for the agent."""
    name = env["AFK_BOT_NAME"]
    email = f"{env['AFK_BOT_ID']}+{name}@users.noreply.github.com"
    run_git(git, env, ["config", "user.name", name])
    run_git(git, env, ["config", "user.email", email])
    writer.set_output("main-sha", run_git(git, env, ["rev-parse", _MAIN]).strip())
    writer.set_output("merge", _merge(git, env))
