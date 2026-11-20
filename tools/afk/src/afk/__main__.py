"""Run one AFK phase: `python3 -m afk <phase>`."""

import argparse
import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from afk import promote_queued
from afk.writer import Runner

PHASES = {"promote-queued": promote_queued.run}


def gh(args: Sequence[str], env: Mapping[str, str]) -> str:
    """Run a `gh` command and return its standard output."""
    return subprocess.run(  # noqa: S603 - ADR 0008 makes the `gh` command line the shell's interface to GitHub
        args, env=dict(env), check=True, stdout=subprocess.PIPE, text=True
    ).stdout


def main(argv: Sequence[str], run: Runner, env: Mapping[str, str]) -> None:
    """Run the phase that `argv` names and append its outputs to `$GITHUB_OUTPUT`."""
    parser = argparse.ArgumentParser(prog="afk")
    parser.add_argument("phase", choices=sorted(PHASES))
    phase = parser.parse_args(argv).phase
    outputs = PHASES[phase](run, env)
    with Path(env["GITHUB_OUTPUT"]).open("a") as output:
        output.writelines(f"{name}={value}\n" for name, value in outputs.items())


if __name__ == "__main__":
    import sys

    main(sys.argv[1:], gh, os.environ)
