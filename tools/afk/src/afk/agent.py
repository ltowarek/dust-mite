"""Refuse the AFK agent's protected changes, and read its error, for every publish."""

import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from afk.git import read_changed_files
from afk.runner import Runner

_LINE_BREAK = re.compile(r"\s*\n\s*")


def protected(paths: Iterable[str]) -> list[str]:
    """Return the changed files under `.github/` or `tools/`, sorted and unique."""
    # Code here runs with the AFK App's write token in later runs (ADR 0008).
    return sorted({path for path in paths if path.startswith((".github/", "tools/"))})


def agent_error(execution: list[dict[str, Any]]) -> str:
    """Return the error that the agent's last message reports, if any."""
    if not execution:
        return ""
    last = execution[-1]
    if last.get("type") != "result" or not last.get("is_error"):
        return ""
    return str(last.get("result") or "")


def already_covered(output: Mapping[str, Any]) -> str:
    """Return the comment section that lists the follow-ups already covered, if any."""
    lines = [
        f"- {_LINE_BREAK.sub(' ', item['problem'])} Covered by #{item['covered_by']}."
        for item in output.get("already_covered") or []
    ]
    if not lines:
        return ""
    return "\n## Follow-ups already covered\n\n" + "\n".join(lines) + "\n"


def read_agent_error(env: Mapping[str, str]) -> str:
    """Return the error in the agent's execution file, if any."""
    execution_file = env.get("AFK_EXECUTION_FILE", "")
    execution = json.loads(Path(execution_file).read_text()) if execution_file else []
    return agent_error(execution)


def refuse_protected_changes(git: Runner, env: Mapping[str, str], base: str) -> None:
    """Fail when an agent commit after `base` changes `.github/` or `tools/`."""
    _refuse(read_changed_files(git, env, base))


def _refuse(changed: Iterable[str]) -> None:
    refused = protected(changed)
    if refused:
        msg = (
            f"Refused to publish: the agent's commits change {', '.join(refused)}. "
            "Code under .github/ and tools/ runs with the AFK App's write token, "
            "so only a human changes it."
        )
        raise SystemExit(msg)
