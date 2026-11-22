"""Run one AFK phase: `python3 -m afk <phase>`."""

import argparse
import logging
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from afk import dispatch, promote_queued, run_check
from afk.writer import Runner, Writer

PHASES = {
    "dispatch": dispatch.run,
    "dispatch-release": dispatch.run_release,
    "promote-queued": promote_queued.run,
    "run-check": run_check.run,
}


def gh(args: Sequence[str], env: Mapping[str, str]) -> str:
    """Run a `gh` command and return its standard output."""
    return subprocess.run(  # noqa: S603 - ADR 0008 makes the `gh` command line the shell's interface to GitHub
        args, env=dict(env), check=True, stdout=subprocess.PIPE, text=True
    ).stdout


def main(argv: Sequence[str], gh: Runner, env: Mapping[str, str]) -> None:
    """Run the phase that `argv` names, with its outputs going to `$GITHUB_OUTPUT`."""
    parser = argparse.ArgumentParser(prog="afk")
    parser.add_argument("phase", choices=sorted(PHASES))
    phase = parser.parse_args(argv).phase
    writer = Writer(gh, env, Path(env["GITHUB_OUTPUT"]))
    PHASES[phase](gh, env, writer)
    writer.report()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main(sys.argv[1:], gh, os.environ)
