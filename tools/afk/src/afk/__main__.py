"""Run one AFK phase: `python3 -m afk <phase>`."""

import argparse
import functools
import logging
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from afk import (
    dispatch,
    finish,
    promote_queued,
    publish,
    run_check,
    run_pr_check,
    run_pr_publish,
)
from afk.writer import Runner, Writer

Phase = Callable[[Mapping[str, str], Writer], None]


def _phases(gh: Runner, git: Runner) -> dict[str, Phase]:
    """Bind each phase to the runners it uses."""
    return {
        "dispatch": functools.partial(dispatch.run, gh),
        "dispatch-release": functools.partial(dispatch.run_release, gh),
        "finish": functools.partial(finish.run, gh),
        "promote-queued": functools.partial(promote_queued.run, gh),
        "publish": functools.partial(publish.run, gh, git),
        "run-check": functools.partial(run_check.run, gh),
        "run-pr-check": functools.partial(run_pr_check.run, gh),
        "run-pr-publish": functools.partial(run_pr_publish.run, git),
    }


def _runner(program: str) -> Runner:
    def run(args: Sequence[str], env: Mapping[str, str]) -> str:
        return subprocess.run(  # noqa: S603 - ADR 0008 makes the `gh` and `git` command lines the shell's interface
            [program, *args],
            env=dict(env),
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        ).stdout

    return run


gh = _runner("gh")
git = _runner("git")


def main(argv: Sequence[str], gh: Runner, git: Runner, env: Mapping[str, str]) -> None:
    """Run the phase that `argv` names, with its outputs going to `$GITHUB_OUTPUT`."""
    phases = _phases(gh, git)
    parser = argparse.ArgumentParser(prog="afk")
    parser.add_argument("phase", choices=sorted(phases))
    phase = parser.parse_args(argv).phase
    writer = Writer(gh, git, env, Path(env["GITHUB_OUTPUT"]))
    phases[phase](env, writer)
    writer.report()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main(sys.argv[1:], gh, git, os.environ)
