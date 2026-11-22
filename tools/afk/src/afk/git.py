"""Run `git` without token variables, read the agent's commits, and push them."""

import base64
from collections.abc import Mapping, Sequence

from afk.github import Token
from afk.runner import Runner


def _authorization(token: str) -> dict[str, str]:
    # Keyed to github.com, so a URL rewrite in the agent's config sends it nowhere else.
    credentials = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
        "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {credentials}",
    }


def run_git(
    git: Runner, env: Mapping[str, str], token: Token | None, args: Sequence[str]
) -> str:
    """Run a git command without token variables, authenticated by `token` if set."""
    # The agent's repository config can run code, so git sees no token variable.
    clean = {
        key: value for key, value in env.items() if key not in {"GH_TOKEN", *Token}
    }
    auth = _authorization(env[token]) if token is not None else {}
    return git(args, {**clean, **auth})


def changed_files(log: str) -> list[str]:
    """Return the files in the NUL-separated `git log` of the agent's commits."""
    return [path for path in log.split("\0") if path]


def read_changed_files(git: Runner, env: Mapping[str, str], base: str) -> list[str]:
    """Return the files that each commit after `base` changes."""
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


def read_commit_count(git: Runner, env: Mapping[str, str], base: str) -> int:
    """Return how many commits HEAD holds after `base`."""
    return int(run_git(git, env, None, ["rev-list", "--count", f"{base}..HEAD"]))


def read_head(git: Runner, env: Mapping[str, str]) -> str:
    """Return the commit that HEAD points at."""
    return run_git(git, env, None, ["rev-parse", "HEAD"]).strip()


def push_args(repository: str, branch: str, lease: str | None) -> list[str]:
    """Return the `git` arguments that push HEAD to `branch`, leased on `lease`."""
    lease_flag = (
        [] if lease is None else [f"--force-with-lease=refs/heads/{branch}:{lease}"]
    )
    # Runs none of the agent's hooks or credential helpers.
    return [
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "credential.helper=",
        "push",
        *lease_flag,
        f"https://github.com/{repository}.git",
        f"HEAD:refs/heads/{branch}",
    ]
