"""Test doubles and readers that the phase tests share."""

import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

__test__ = False


Call = TypeVar("Call")


class _Spy(Generic[Call]):
    """Record a program's calls, answer its reads from canned output, and fail."""

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
        self.calls: list[Call] = []

    def _answer(self, args: list[str]) -> str:
        if (
            self._failing is not None
            and tuple(args[: len(self._failing)]) == self._failing
        ):
            raise subprocess.CalledProcessError(1, args)
        prefixes = [p for p in self._answers if tuple(args[: len(p)]) == p]
        return self._answers[max(prefixes, key=len)] if prefixes else ""


@dataclass(frozen=True)
class GhCall:
    """One `gh` call's arguments, and the token and repository it ran with."""

    args: list[str]
    token: str
    repo: str


class GhSpy(_Spy[GhCall]):
    """Record every `gh` call."""

    def __call__(self, args: Sequence[str], env: Mapping[str, str]) -> str:
        """Record the call, then answer or fail it."""
        args = list(args)
        self.calls.append(GhCall(args, env["GH_TOKEN"], env["GH_REPO"]))
        return self._answer(args)


@dataclass(frozen=True)
class GitCall:
    """One `git` call's arguments, and the configuration its environment added."""

    args: list[str]
    config: dict[str, str]


class GitSpy(_Spy[GitCall]):
    """Record every `git` call, and refuse one that carries a token variable."""

    def __call__(self, args: Sequence[str], env: Mapping[str, str]) -> str:
        """Record the call, then answer or fail it."""
        args = list(args)
        tokens = {"GH_TOKEN", "AFK_APP_TOKEN", "AFK_WORKFLOW_TOKEN"} & env.keys()
        if tokens:
            msg = f"git ran with {sorted(tokens)}"
            raise ValueError(msg)
        count = int(env.get("GIT_CONFIG_COUNT", "0"))
        config = {
            env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"]
            for i in range(count)
        }
        self.calls.append(GitCall(args, config))
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
