"""Run one AFK phase: `python3 -m afk <phase>`."""

import argparse
import logging
import os
import secrets
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TextIO

from afk import promote_queued
from afk.writer import Runner, StepOutput

PHASES = {"promote-queued": promote_queued.run}


def gh(args: Sequence[str], env: Mapping[str, str]) -> str:
    """Run a `gh` command and return its standard output."""
    return subprocess.run(  # noqa: S603 - ADR 0008 makes the `gh` command line the shell's interface to GitHub
        args, env=dict(env), check=True, stdout=subprocess.PIPE, text=True
    ).stdout


def write_outputs(output: TextIO, outputs: Mapping[str, str]) -> None:
    """Write step outputs in the multiline form, so no value can add an output."""
    delimiter = f"afk_{secrets.token_hex(16)}"
    output.writelines(
        f"{name}<<{delimiter}\n{value}\n{delimiter}\n"
        for name, value in outputs.items()
    )


def step_output(path: Path) -> StepOutput:
    """Return a writer that appends step outputs to `path` as soon as it is called."""

    def write(outputs: Mapping[str, str]) -> None:
        # Append: earlier writes in the same step stay outputs.
        with path.open("a") as output:
            write_outputs(output, outputs)

    return write


def main(argv: Sequence[str], gh: Runner, env: Mapping[str, str]) -> None:
    """Run the phase that `argv` names, with its outputs going to `$GITHUB_OUTPUT`."""
    parser = argparse.ArgumentParser(prog="afk")
    parser.add_argument("phase", choices=sorted(PHASES))
    phase = parser.parse_args(argv).phase
    PHASES[phase](gh, env, step_output(Path(env["GITHUB_OUTPUT"])))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main(sys.argv[1:], gh, os.environ)
