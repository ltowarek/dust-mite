# Spec gaps

An AFK agent session that finds a spec gap stops and asks in writing. It never guesses and never waits for an answer. The decision and its reasons are in [Decide what an AFK agent session does at a spec gap](https://github.com/ltowarek/dust-mite/issues/263).

## What counts

A spec gap is defined in [GLOSSARY.md](../../GLOSSARY.md). The ADRs count as docs. A question counts only when reasonable answers give results that the maintainer would see in review.

Anything that the agent would have to write in the PR as "I assumed X" is a spec gap.

A ticket that needs a test but names no seam, in itself or in its spec, has a spec gap.

## When to look

- Before writing any code, check the agent brief against the code and the docs.
- A gap found later still stops the session.
- Each stop asks every gap that the agent can state by then, not only the first. A gap that depends on the answer to another gap waits for the next run.

## What happens to the work

The session discards its work: no commits, no branch and no PR. What the session learned goes into the comment.

## The ticket

- **AFK run:** the agent writes the comment in its structured output, from `## What the run established` to the end, and changes nothing on GitHub. The workflow adds the first line with the run link, posts the comment on the ticket, removes `ready-for-agent` and adds `needs-triage`.
- **Car agent session:** the session posts the comment without the run link and swaps the labels with `gh` itself, keeps `needs-car:<variant>` on the ticket, and moves on to the next item.

The ticket is not picked again until the maintainer triages it. `/triage` posts a new full agent brief that supersedes the old one and applies `ready-for-agent` again. The latest agent brief is the contract.

## Comment format

```markdown
> *Spec gap found by an AFK agent session while working this ticket.* ([run](<url>))

## What the run established

- <facts found: causes, code paths, what the brief already settles>

## Spec gaps

1. **<question>**: <options>. Recommended: <option>, because <reason>.
   Evidence: <the brief's words against file:line, a doc, or an ADR>
```
