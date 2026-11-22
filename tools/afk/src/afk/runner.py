"""Run `gh` or `git` as a subprocess; tests pass a spy in its place."""

import subprocess
from collections.abc import Callable, Mapping, Sequence

# Runs one program; its arguments leave out the program name.
Runner = Callable[[Sequence[str], Mapping[str, str]], str]


def runner(program: str) -> Runner:
    """Return a runner that runs `program` and returns its standard output."""

    def run(args: Sequence[str], env: Mapping[str, str]) -> str:
        return subprocess.run(  # noqa: S603 - ADR 0008 makes the `gh` and `git` command lines the shell's interface
            [program, *args],
            env=dict(env),
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        ).stdout

    return run
