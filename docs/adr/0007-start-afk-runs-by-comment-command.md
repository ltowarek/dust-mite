# Start AFK runs by comment command; keep labels for state

The maintainer started every AFK run by adding a label: `agent:implement` on a ticket, a spec or a PR, or `agent:update-branch` on a PR. The two PR workflows triggered on `pull_request_target`, because GitHub does not fire `pull_request` on a PR that conflicts with `main`. From 2026-12-02 GitHub blocks `pull_request_target` in public repositories by default, so labelling a PR would start nothing ([#342](https://github.com/ltowarek/dust-mite/issues/342)). The labels also did two jobs at once: `agent:implement` was both the request for a run and the state "a run is queued or running", and the App re-added it to chain a spec's sub-issues.

The maintainer therefore starts an AFK run with an AFK command: a new conversation comment whose first line is `/afk implement` or `/afk update-branch`. A dispatcher workflow on `issue_comment` accepts a command only from the repository owner, matched by account id, records the state in an `afk:*` label, reacts to the comment and dispatches the matching run workflow. The run workflows trigger on `workflow_dispatch` only, which runs on a conflicting PR, is not affected by the `pull_request_target` block, and lets a run dispatch the next one in a spec's chain with `GITHUB_TOKEN`. Labels record state only: `afk:queued`, `afk:in-progress` and `afk:blocked`.

Comment commands are what the first-party agents in Actions use, such as `claude-code-action`, `run-gemini-cli` and gh-aw's `slash_command` ([research notes](../research/afk-loop-triggers.md)). zizmor's `dangerous-triggers` audit and GitHub Security Lab instead recommend label gates over `issue_comment`, because GitHub does not restrict who may comment and a comment does not pin the code it approves. The dispatcher answers both concerns: it ignores every commenter but the owner, and an AFK run on a PR checks out the head commit recorded when the command was accepted and pushes with a lease against it. The dispatcher's `issue_comment` trigger therefore carries a `zizmor: ignore[dangerous-triggers]` comment with this reason.

## Considered Options

- **A repository Actions event policy that allows `pull_request_target`.** Rejected: it keeps a trigger that is also state, and it depends on a policy outside the repository's files.
- **`@dust-mite-afk` mentions.** Rejected: no user `dust-mite-afk` exists, and anyone who registered that login later would be notified of every command.
- **Labels as triggers through `issues` and `pull_request: labeled`.** Rejected: `pull_request` does not fire on a PR that conflicts with `main`, which is the PR that `update-branch` exists for.
- **Assigning the ticket to the App's bot.** Rejected: GitHub does not allow a custom App's bot as an assignee.

## Consequences

- A command from anyone but the owner, an edited comment and a review comment start nothing.
- A failed run labels its target `afk:blocked`; a new command clears it.
- The dispatcher's `GITHUB_TOKEN` needs `actions: write` to dispatch, and the AFK App keeps Actions read, so a leaked App token cannot start workflows.
- A run started from the Actions tab sets and clears `afk:in-progress` itself, so the label is correct however the run started.
