"""Test doubles and readers that the phase tests share."""

import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

__test__ = False


class _Spy:
    """Answer one program's reads from canned output, and fail on request."""

    program: str

    def __init__(
        self,
        answers: Mapping[tuple[str, ...], str] | None = None,
        failing: tuple[str, ...] | None = None,
    ) -> None:
        """Answer a call with the output of the longest `answers` prefix it starts with.

        A call that starts with `failing` raises; any other call answers "".
        """
        self._answers = answers or {}
        self._failing = failing

    def _answer(self, args: list[str]) -> str:
        if args[0] != self.program:
            msg = f"Not a {self.program} command: {args}"
            raise ValueError(msg)
        if (
            self._failing is not None
            and tuple(args[: len(self._failing)]) == self._failing
        ):
            raise subprocess.CalledProcessError(1, args)
        prefixes = [p for p in self._answers if tuple(args[: len(p)]) == p]
        return self._answers[max(prefixes, key=len)] if prefixes else ""


@dataclass(frozen=True)
class GhCall:
    """One `gh` command line, and the token and repository it ran with."""

    args: list[str]
    token: str
    repo: str


class GhSpy(_Spy):
    """Record every `gh` call, and refuse any other program's."""

    program = "gh"

    def __init__(
        self,
        answers: Mapping[tuple[str, ...], str] | None = None,
        failing: tuple[str, ...] | None = None,
    ) -> None:
        """Answer and fail calls as `_Spy` does."""
        super().__init__(answers, failing)
        self.calls: list[GhCall] = []

    def __call__(self, args: Sequence[str], env: Mapping[str, str]) -> str:
        """Record the call, then answer or fail it."""
        args = list(args)
        self.calls.append(GhCall(args, env["GH_TOKEN"], env["GH_REPO"]))
        return self._answer(args)


@dataclass(frozen=True)
class GitCall:
    """One `git` command line, and the token it ran with, if any."""

    args: list[str]
    token: str


class GitSpy(_Spy):
    """Record every `git` call, and refuse any other program's."""

    program = "git"

    def __init__(
        self,
        answers: Mapping[tuple[str, ...], str] | None = None,
        failing: tuple[str, ...] | None = None,
    ) -> None:
        """Answer and fail calls as `_Spy` does."""
        super().__init__(answers, failing)
        self.calls: list[GitCall] = []

    def __call__(self, args: Sequence[str], env: Mapping[str, str]) -> str:
        """Record the call, then answer or fail it."""
        args = list(args)
        self.calls.append(GitCall(args, env.get("GH_TOKEN", "")))
        return self._answer(args)


_OUTPUT = re.compile(
    r"(?P<name>[^\n<]+)<<(?P<delimiter>\S+)\n(?P<value>.*?)\n(?P=delimiter)\n",
    re.DOTALL,
)


def read_outputs(path: Path) -> dict[str, str]:
    """Return the step outputs in `path`, in the multiline form; the last one wins."""
    if not path.exists():
        return {}
    return {m["name"]: m["value"] for m in _OUTPUT.finditer(path.read_text())}
