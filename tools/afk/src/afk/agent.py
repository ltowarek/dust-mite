"""Read the AFK agent's commits and its error, which every publish phase checks."""

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from afk.writer import Runner, run_git


def protected(paths: Iterable[str]) -> list[str]:
    """Return the changed files under `.github/` or `tools/`, sorted and unique."""
    # Code here runs with the AFK App's write token in later runs (ADR 0008).
    return sorted({path for path in paths if path.startswith((".github/", "tools/"))})


def changed_files(log: str) -> list[str]:
    """Return the files in the NUL-separated `git log` of the agent's commits."""
    return [path for path in log.split("\0") if path]


def agent_error(execution: list[dict[str, Any]]) -> str:
    """Return the error that the agent's last message reports, if any."""
    if not execution:
        return ""
    last = execution[-1]
    if last.get("type") != "result" or not last.get("is_error"):
        return ""
    return str(last.get("result") or "")


def read_agent_error(env: Mapping[str, str]) -> str:
    """Return the error in the agent's execution file, if any."""
    execution_file = env.get("AFK_EXECUTION_FILE", "")
    execution = json.loads(Path(execution_file).read_text()) if execution_file else []
    return agent_error(execution)


def _read_changed_files(git: Runner, env: Mapping[str, str], base: str) -> list[str]:
    # Per commit and unquoted; replace refs could hide a commit that the push sends.
    args = [
        "--no-replace-objects",
        "log",
        "-z",
        "--format=",
        "--name-only",
        "--no-renames",
        "--diff-merges=first-parent",
        f"{base}..HEAD",
    ]
    return changed_files(run_git(git, env, None, args))


def refuse_protected_changes(git: Runner, env: Mapping[str, str], base: str) -> None:
    """Fail when an agent commit after `base` changes `.github/` or `tools/`."""
    refused = protected(_read_changed_files(git, env, base))
    if refused:
        msg = (
            f"Refused to publish: the agent's commits change {', '.join(refused)}. "
            "Code under .github/ and tools/ runs with the AFK App's write token, "
            "so only a human changes it."
        )
        raise SystemExit(msg)


def read_head(git: Runner, env: Mapping[str, str]) -> str:
    """Return the commit that the agent's work ends at."""
    return run_git(git, env, None, ["rev-parse", "HEAD"]).strip()
