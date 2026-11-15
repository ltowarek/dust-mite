# Follow-up tickets

An AFK agent session files a follow-up ticket for a problem that it can show in code its pull request did not change, unless a ticket or pull request already covers that problem. The decision and its reasons are in [Decide how AFK agent sessions file follow-up tickets without duplicates](https://github.com/ltowarek/dust-mite/issues/262).

## What qualifies

- A problem qualifies when the agent can show it with a code path, a command and its output, or the documented rule that the code breaks. Problems in CI and in the devcontainers qualify.
- Ideas, improvements, Fowler smells from the `/code-review` baseline, and failures of the run itself do not qualify.

## Fix or file

- A finding on a line that the diff adds or modifies is fixed in the pull request.
- A finding anywhere else becomes a follow-up ticket, even a one-line fix next to the change.
- A refactor commit that [CLAUDE.md](../../CLAUDE.md) asks for counts as changed code.
- A problem that blocks the ticket is a spec gap, not a follow-up ticket.

## Duplicates

- Search open and closed tickets and open pull requests by domain concept, using the terms in [GLOSSARY.md](../../GLOSSARY.md), as `/triage` does.
- File nothing when an open ticket, a ticket closed as not planned, or an open pull request already covers the problem. Do not comment on the matching ticket either; record the match as a follow-up already covered.
- When a ticket closed as completed covers the problem, file the follow-up ticket anyway and end its Problem section with `Possibly a regression of #M.`

## Labels

Every follow-up ticket carries `needs-triage` and `source:follow-up`, plus the agent's best guess at one type label and at least one component label from [CONTRIBUTING.md#issue-labels](../../CONTRIBUTING.md#issue-labels). There is no cap on follow-up tickets per run. The query `label:source:follow-up label:wontfix` counts the follow-up tickets that end up `wontfix`.

## Body

The title names the problem in plain words. The body has this format:

```markdown
> *Follow-up ticket filed by an AFK agent session while working #N.* ([run](<url>))

## Problem

<what is wrong, in one paragraph>

## Evidence

<the code path (file:line), the command and its output, or the rule it breaks and where the repo states it>
```

A car agent session leaves out the run link.

## Who files

- **AFK run:** the agent files nothing itself. It lists each follow-up ticket in `follow_ups`, with the title, the type and component labels, and a body that starts at `## Problem`. It lists each follow-up already covered in `already_covered`, with the problem and the number of the ticket or pull request that covers it. The [AFK run workflow](../../.github/workflows/afk-run.yml) adds the origin line and the labels, files the tickets whether or not the run opened a pull request, and posts the follow-ups already covered, one line each, as one comment on the pull request or, at a spec gap or when finding the fix needs the car, under their own heading in the comment on the ticket.
- **Car agent session:** the session files each follow-up ticket with `gh` itself and applies the labels.
