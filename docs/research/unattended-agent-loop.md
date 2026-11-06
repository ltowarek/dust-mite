# Unattended coding agents on GitHub issues under Claude Pro

Research notes, 2026-11-05. All sources were read on that date. `docs/research/` held no prior notes, so this path is new. Every citation is an inline link. Items marked *beta* come from `skills/in-progress` and are not part of the released skill set.

## 1. Summary

- Three shapes are in use: a CI job that runs an agent CLI per ticket, a vendor cloud agent, and a local orchestrator or loop. Matt Pocock's own repository uses the first shape, with a label trigger, GitHub Actions and `CLAUDE_CODE_OAUTH_TOKEN` ([workflow][sc-wf]).
- Matt's released guidance is direct: for truly AFK work "a deterministic loop (Sandcastle, a shell script, a CI job) is faster, cheaper, and more reliable, because no agent makes the orchestration decisions" ([implement-spec docs][m-spec-doc]).
- On Pro, the serial skill is `/implement`, not `/implement-spec`. On a one-at-a-time harness the latter "is only a slower `implement`" ([same page][m-spec-doc]).
- Pro works without API billing for `claude-code-action` ([docs][gha]), cloud scheduled tasks ([docs][routines]), Projects ([docs][projects]), `claude -p` ([support article][sdk-plan]) and Sandcastle ([docs][sc-start]). GitHub Agentic Workflows does not: "A Claude subscription OAuth login is not supported" ([docs][aw-claude]).
- Terms: the Consumer Terms forbid automated access "except" via an API key "or where we otherwise explicitly permit it" ([terms][terms]). Anthropic documents several subscription automation paths, but no text states that a recurring unattended loop on Pro falls inside that exception. Section 3.2 quotes the wording.
- Usage limits: nothing in the unattended Pro paths waits by default, except a Projects thread you started yourself. A clock that retries is the simplest answer ([routines][routines], [Projects][projects]).
- Review time: the strongest evidence supports small changes, passing checks before review, and a limit on open work. Evidence for AI pre-review is mixed. No controlled study of `/pr`-style bodies was found.
- Shortlist: **(A)** extend the existing `claude-code-action` workflow, one ticket per run. **(B)** a cloud scheduled task. Start with A. Section 5 gives the staged path.
- Prerequisite: 0 of the 41 open issues carry `ready-for-agent` today ([repo state](#repo-facts-checked-today)). No loop has input until tickets are triaged.

## 2. What Matt Pocock actually recommends for AFK work

### Released skills and docs (current, November 2026)

- **Chain:** `to-spec → to-tickets → implement → code-review → pr → retro` ([pr docs][m-pr-doc]). `to-tickets` applies `ready-for-agent` when it publishes, "so an AFK runner picks them up without another pass" ([triage docs][m-triage-doc]).
- **Agent brief:** the contract an AFK agent works from. It is durable, behavioural, has testable acceptance criteria and explicit scope, and avoids file paths and line numbers ([AGENT-BRIEF][m-brief]).
- **`/implement`** fetches the ticket, runs `tdd` at agreed seams, runs `code-review`, then commits to the current branch. It does not open a PR ([skill][m-impl], [pr docs][m-pr-doc]). A non-trivial ticket above 100k tokens "is normal"; the fix is to split the ticket ([docs][m-impl-doc]).
- **`/implement-spec`** runs tickets at once across a frontier and needs background subagents ([docs][m-spec-doc]). Its docs report one five-ticket run where "the review and fix loop took roughly four hours". That is a poor fit for a Pro budget.
- **Blocking edges:** native GitHub dependencies, with a [REST API][deps], read with `issue_dependencies_summary.blocked_by`, which counts open blockers only ([tracker template][m-tracker]). "The tracker's blocked-by count only drops when a blocker *closes*" ([docs][m-spec-doc]). With a human merge gate, a dependent ticket therefore waits for its blocker's merge.
- **Sandcastle or a script still has a role:** the docs answer "Does this replace Sandcastle or an AFK script?" with "No" ([docs][m-spec-doc]).

### `/pr`, read in full

It defines a body format and does nothing else. It does not push, open a PR, or read `.github/pull_request_template.md` ([skill][m-pr], [docs][m-pr-doc]). The template has three sections:

- **Summary:** "the smallest view that makes the key point clear": pseudocode, call tree, component tree, file tree, Mermaid, or a shaped diff. The menu comes from Dex Horthy's `show-me` ([credits][m-pr-credits]).
- **Evidence:** a before and after. Screenshots are "S-tier", execution output "A-tier". "'Tests are green' on its own is a claim" ([docs][m-pr-doc]).
- **Merge Danger:** a one-way or two-way **Door** and a one-word **Blast Radius**. The docs state its purpose: "Skim a two-way door with a small blast radius, and read a one-way door slowly." They also warn that the author is grading itself, so be most suspicious of "two-way, small blast radius", and suggest listing the changes a repo always treats as one-way ([docs][m-pr-doc]).

It is usable as the review summary. It is released but not installed locally, and it is model-invoked, so an agent should reach for it once it is available ([README][m-readme]). The repo has no PR template, so the two do not compete.

### Ralph material (January 2026, older than the above)

- The Ralph loop originates with Geoffrey Huntley: "In its purest form, Ralph is a Bash loop" (14 July 2025, [source][ralph]). He warns of waking "to a broken codebase" and recommends greenfield use.
- Matt's guides: start human-in-the-loop, then go AFK; "For AFK Ralph, always cap your iterations"; a sandbox is "essential insurance" for overnight loops; "Ralph triages, implements, and opens the PR. You review when you're ready." ([tips][m-tips], [guide][m-ralph], both updated 2026-01-08).
- **Plan caveat:** "I'm on the Anthropic 5x Max plan at around £90/month" ([tips][m-tips]). None of Matt's sources read addresses Pro budgets.

### Sandcastle (v0.14.0, 2026-11-02, pre-1.0, MIT)

- A TypeScript library wrapping agent CLIs in sandboxes ([README][sc-readme]). Getting started uses `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` ([docs][sc-start]).
- `sequential-reviewer` is the serial template: a [ten-iteration loop][sc-seq-main], implement then review, with a Node-specific [prompt][sc-seq]. Its prompt tells the agent to pick "the highest-priority open issue that is not blocked", so ticket selection there is an agent decision.
- "Sandcastle does not retry on provider errors (rate limits, auth failures, quota errors, network timeouts, etc.)" ([decision][sc-retry]). Limit handling is left to the caller.
- Nested Docker is not covered in its docs (sandbox-provider guide searched for socket and docker-in-docker). A dust-mite agent needs `docker exec` into devcontainers.
- **Its own CI shows the simple shape** ([workflow][sc-wf]): `agent:implement` label → refuse parent or child issues → refuse if a PR already targets the issue → label `agent:in-progress` → branch → run agent with [`noSandbox()`][sc-impl] (the runner is the sandbox) → push → open **draft** PR → label for automated review → on failure, label `agent:blocked` with a reason. About 200 lines of YAML, and the orchestration is all deterministic.
- `.factory/` shows a daemon contract, but the daemon lives in `~/repos/ai/software-factory` ([script][sc-daemon]), and `mattpocock/software-factory` returns 404. It cannot be read.

### `software-factory` (*beta*, not for use as the workflow; added 2026-10-31)

A glossary skill for designing such a system ([skill][m-sf], [runners survey][m-sf-run]). Useful ideas:

- "Every trigger is an accelerator. Accelerators without brakes make a slop cannon." The brakes are automated checks, automated review and human review.
- "Add one automated trigger at a time, throttled at first", and "cap every loop of runs at a few tries before a human".
- "A run never waits for a human: it ends, and the human's later change to the ticket tracker or git host triggers a new run."
- Its "All on GitHub" design fills orchestrator, runner and observability with GitHub Actions alone.
- Five questions for each task: trigger, reads and writes, next trigger, human re-entry, and "What stops two runs doing the same work?"

## 3. Options

Letters are referenced from section 5. Money means extra cost on top of Pro.

### 3.1 Comparison

| Option | Pro without API billing | Terms status (3.2) | PC off | Docker, 6.7 GB image | Serial queue, usage limit | Picks issues, honours blocking | Human merge | Setup | Upkeep | Money | Teaches |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **A. `claude-code-action`**, one ticket per run | Yes ([token on Pro][gha]) | Documented path; cron examples apply to OAuth ([docs][gha]) | Yes | Same runner class as CI: [4 vCPU, 16 GB, 14 GB SSD][runner]; [6 h job cap][limits] | Concurrency group; [one pending by default, queue opt-in][conc]. No documented wait at a limit; treat as a failed run, next clock tick retries | Nothing built in. YAML filters by label and [open-blocker count][m-tracker] | Good: ["does not merge"][a-faq] (a system-prompt rule), no PR by default; YAML opens the draft | Low: secret and workflow exist; add a job | Low | $0: [free on public repos][billing] | Events, least privilege, deterministic orchestration |
| **B. Cloud scheduled task** (research preview) | Yes ([plans][features]) | First-party: "Put Claude Code on autopilot" ([docs][routines]) | Yes ([docs][routines]) | [`docker` and compose pre-installed, 4 vCPU, 16 GB, 30 GB][cloud]; ghcr.io and Docker Hub on [Trusted list][cloud]; setup cached only if under about 5 min | Clock, [minimum 1 h][sched]. At a limit "additional runs are rejected until your usage window resets" ([docs][routines]); overlap not documented | Agent decides. [`gh issue` and `gh pr` get 403][cloud]; use built-in tools or `gh api`. Issue events exist, [filters documented for PRs only][routines] | Weak: runs [act as you][routines]; a prompt, not a control | Lowest: web form or `/schedule`; [commit skills to repo][skills] | Low; preview may change | $0: [no VM charge][web] | Cloud env, network allowlists, little about orchestration |
| **C. Claude Code Projects** (public beta) | Yes, [rolling out, may need waitlist][projects] | First-party | Yes for cloud threads | As B; [repo skills not loaded in threads][projects] | Parallel by design; a thread limit "is a preference rather than a cap". Threads [retry until reset][projects]; those a scheduled task started do not | Conversation-driven; no issue queue | Weak: instructions only; [has a **Merge it** button][projects] | Low | Low | $0 | Delegation style; hides mechanics |
| **D. Local `claude -p` loop** (Ralph-style script) | Yes ([article][sdk-plan]) | Docs describe ["shell loops"][bp]; subscription token ["for CI pipelines, scripts"][auth] | **No** | Native, as today; 7.7 GB RAM competes with builds | A `for` loop. [`-p` exits non-zero][headless]; workflows [do not pause in `-p`][workflows]. Script must wait. Interactive sessions [wait, up to three times][interactive] | Script with `gh` | Good with a hook guardrail ([`git-guardrails-claude-code`][m-guard], frozen `misc/` skill) | Lowest: about 20 lines | Low; see [`--bare` risk](#6-what-the-sources-did-not-settle) | $0 | The whole loop, most directly |
| **E. Sandcastle** | Yes ([docs][sc-start]) | Runs the unmodified CLI ([legal][legal]) | Only inside Actions or a cloud sandbox | `docker()` builds its own image; nested Docker undocumented | `sequential-reviewer`; [no retry on limits][sc-retry] | Yes, but agent picks ([template][sc-seq]) | Configure branch strategy; README: commits ["get merged back"][sc-readme] | Medium: Node and TS dependency, custom Dockerfile, rewrite prompts | Medium: pre-1.0 | $0 | Orchestration shapes, Matt's stack |
| **F. Self-hosted runner on the PC** | As A | As A | **No** | Native | As A | As A | As A | Medium | Medium | $0 ([billing][billing]) | Runner security |
| **G. Codespaces + Claude Code** | Yes, as D | As D | Yes, until limits below | [Repo `.devcontainer` subfolders supported][cs-dev]. [Free 120 compute hours, scaled by cores, 15 GB][cs-billing]; [idle 240 min max, 12 h lifetime][cs-idle] | None: an environment, not a queue | None | As D | Medium | Medium | $0 inside quota | Devcontainer portability |
| **H. Copilot coding agent** | **No**: Claude agent runs on [Copilot subscription][cp-third] | Not applicable | Yes | [Actions-based, custom setup][cp-agent] | Vendor-run; credits | [Assign an issue][cp-plans] | Vendor flow | Low | Low | [≥ $10/mo][cp-plans] | A second vendor's flow |
| **I. GitHub Agentic Workflows** | **No**: [API key or Copilot inference][aw-claude] | Not applicable | Yes | Actions | Actions | Markdown spec | [Safe outputs][aw-safe] | Medium | Medium | API or Copilot cost | Least-privilege agent design |
| **J. cezar / OpenHands** (third party) | Reportedly yes, via the CLI | CLI login allowed ([legal][legal]); route must be unmodified CLI | Only on a VPS | Local | Cezar: [queue, worktrees][cezar]; reported reset-aware start | Cezar: [one-click issue, "Nothing merges on its own"][cezar] | Good | Medium | Medium | VPS for PC-off | An app's concepts |

Notes on F and G. GitHub states "self-hosted runners should almost never be used for public repositories on GitHub" ([hardening guide][gh-sec]); the repository is public. A codespace's idle timer resets on terminal output ([docs][cs-idle]), so a long unattended agent run depends on that side effect.

### 3.2 Terms of service

Consumer Terms section 3 lists prohibited uses, including: "Except when you are accessing our Services via an Anthropic API Key or where we otherwise explicitly permit it, to access the Services through automated or non-human means, whether through a bot, script, or otherwise." ([terms][terms], effective Oct 8, 2025, which govern Pro [per the legal page][legal]).

Other Anthropic text on the same point:

- "Advertised usage limits for Pro, Max, and Ultra plans assume ordinary, individual usage of Claude Code and the Agent SDK." ([legal][legal])
- OAuth "is designed to support ordinary use of Claude Code and other native Anthropic applications." The restriction does not "prevent an end user from signing in to the unmodified Claude Code binary with their own Claude subscription". ([legal][legal])
- "Anthropic reserves the right to take measures to enforce these restrictions and may do so without prior notice." ([legal][legal])
- `claude setup-token`: "For CI pipelines, scripts, or other environments where interactive browser login isn't available", requiring "a Pro, Max, Ultra, Team, or Enterprise plan". ([auth][auth])
- "Claude Agent SDK, `claude -p`, and third-party app usage still draw from your subscription limits." (June 15, 2026; the earlier-announced change was paused) ([support][sdk-plan])
- Usage Policy, effective Nov 12, 2026, one week from now: do not "Resell, proxy, or otherwise provide access to Claude through unauthorized means, including services that route requests through consumer subscriptions or misrepresent the product or client being used". ([policy][aup]) This targets proxies and misrepresentation.

**Reading (mine, not legal advice).** B and C are first-party products documented for unattended work on Pro. A and D are documented in Anthropic's own docs with a subscription token, which is the best available reading of "explicitly permit". E and J are acceptable only while they run the unmodified CLI with the owner's own login. **No Anthropic text says a recurring, unattended, scheduled loop on Pro counts as "ordinary, individual usage".** Conservative posture: one person, one token, serial, low frequency, usage credits off, no proxy.

### 3.3 Trends (one line each)

| Tool | Status | Hobby-simple? |
| --- | --- | --- |
| [Gas Town][gastown] | Active multi-agent orchestrator with mailboxes and identities | No: swarm shape, wrong for Pro |
| [Conductor][conductor] | Parallel workspaces "on your Mac" | No: this PC runs Linux |
| [Vibe Kanban][vk] | README: "sunsetting"; [company closed April 2026][vk-end] | No: avoid |
| [container-use][cu] | "experimental" badge; last push Sept 2026 | Marginal: devcontainers already do this |
| [Symphony][symphony] (OpenAI) | "low-key engineering preview"; a spec to implement; demo on Linear | No, but worth reading |
| [Codex cloud][codex], [Cursor cloud agents][cursor] | Other vendors; Cursor needs Premium or higher | Simple, but not Pro and adds cost |
| [Hive Mind][hive] | Small (93 stars); `claude -p` host | No |
| [Agent teams][teams], [dynamic workflows][workflows] | Experimental and token-heavy; workflows pause only in interactive sessions | No: parallelism again |
| [Remote Control][rc], [agent view][agent-view], [`/loop`][sched], [`/goal`][goal] | Local aids; PC must stay on. Remote Control is on Pro | Yes for PC-on sessions and hardware tickets |
| [`claude --cloud`, auto-fix][web] | One-shot cloud sessions on Pro; auto-fix answers CI failures and review comments | Yes, but a human dispatches each task |
| [Self-hosted environments][selfhost] | Anthropic control plane, own compute; Team and Enterprise only | No: not on Pro |

## 4. Reducing review time

| Practice | Evidence | Strength | Apply here |
| --- | --- | --- | --- |
| Small changes | DORA: "large changes are difficult to review", the discipline "is especially important when using AI coding assistants", avoid large generated PRs ([capability][dora-batch]). 33k agent PRs: unmerged ones "tend to involve larger code changes" and "often do not pass" CI ([study][pr-fail]). 200 to 400 LOC per review ([SmartBear/Cisco][smartbear], vendor; date not checked) | High for direction; the number is weak | One ticket, one PR. Split at `to-tickets`. Refuse or flag oversize diffs mechanically |
| Green checks before review | Without strong automated testing, version control and fast feedback, more change volume leads to instability; "AI doesn't fix a team; it amplifies what's already there" ([DORA 2025][dora-2025]). | High | CI must run before the human reads. See CI on agent drafts below |
| Limit open work | "WIP limits help drive improvements in software delivery performance" ([DORA][dora-wip]). Rejection reasons include "lack of meaningful reviewer engagement" and "duplicate PRs" ([study][pr-fail]) | Medium: team data | Start at one open agent PR; a clock tick exits otherwise |
| Choose low-risk task types first | Docs 82.1% accepted against 66.1% for features ([study][pr-task]) | Medium | Docs and refactors first; observational data |
| Reader-first summary | Practitioner guidance only ([`/pr`][m-pr-doc]). No controlled study found | Low, cheap to try | Use `/pr`; define repo one-way doors (flash layout, wire protocol, CI config) |
| Order what is read | File position matters: earlier files get more comments across 219,476 PRs; 64% lower odds of finding one defect type in the last file ([Fregnan et al., FSE 2022][fregnan]) | Medium: one defect type in the experiment | Name files to read first in Summary; the paper notes GitHub orders files alphabetically |
| AI pre-review | 73.8% of comments resolved, but average PR closure rose from about 5 h 52 min to 8 h 20 min ([Cihan et al., ICSE-SEIP 2025][cihan]). Vendor: substantive comments 16% to 54%; 84% of PRs over 1,000 lines get findings against 31% under 50 ([Anthropic][cr-post], internal). Warning: "A reviewer that's asked to find problems will always find *something*" ([best practices][bp]) | Mixed | One pass, fresh context, correctness only, one fix round. Measure whether it saves human time. Managed Code Review is [not on Pro][cr-docs]. Anthropic's local `/code-review` is a lighter version of it ([Claude Code team][cc-review]), and is a different thing from Matt's skill with the same name |
| Stacked PRs | GitHub native stacks in [public preview since 2026-07-30][stack]; [rollout doc][stack-doc]; [open defects][stack-bug]. No controlled review-time study found | Low for this use | Not needed serially: blocked tickets already wait for the merge |
| Track the right metric | Meta: P75 Time In Review, guarded by Eyeball Time against rubber-stamping; nudges cut time 7%, next-diff queue raised review actions 17% ([Meta][meta]) | Medium: large team | Track time-to-review and whether a later fix reverted the PR. Stop if reading time collapses |
| Fix recurring findings at the source | The Claude Code team fixes a finding that keeps coming back "in the skill, with a lint rule, or with updates to instructional files" such as `CLAUDE.md` and `REVIEW.md` ([Claude Code team][cc-review]) | Low: practice, no figure | [#270](https://github.com/ltowarek/dust-mite/issues/270): a rule that keeps causing review arguments gets a check or a line in a standards file |
| Stop review rounds early | "Noise costs more when the author is an agent": an agent fixes every nit, which means another commit and another round. With a cap of three rounds and diff-only re-review, PRs passing after one round rose from 65% to 78%, PRs needing five or more rounds fell from 8.9% to 1.5%, and mean reviews to pass fell from 2.08 to 1.32. About 59% of what the reviewer kept flagging was code already there at its first pass ([Claude Code team][cc-review], internal) | Medium: vendor's internal data | Keep one pre-review pass and one fix round. Findings in code the PR didn't change become follow-up tickets ([#262](https://github.com/ltowarek/dust-mite/issues/262)), not fixes in the same PR |
| Short review guidance | A good `REVIEW.md` says what failure looks like in the repo, caps nits, lists paths to skip, asks for a file and line as evidence, and starts its summary with a count ([Claude Code team][cc-review]) | Low: practice | Matt's `/code-review` reads any repo file that documents how code should be written. Where the rules live is [#270](https://github.com/ltowarek/dust-mite/issues/270) |
| Paths that always need a person | CI workflow files and paths owners mark as sensitive always need a person. An agent's approval "never counts as a person's", and an approval covers one commit, so an agent's later push needs a new one ([Claude Code team][cc-review]) | Low: team policy | Already true here, since I review every PR. [#267](https://github.com/ltowarek/dust-mite/issues/267) could make GitHub enforce it |
| Explainers over trivial diffs | "A one-line copy change teaches you almost nothing. An explainer for the module you're about to change teaches you a lot" ([Claude Code team][cc-review]) | Low: opinion | Fits the learning goal: the PR body could explain the unfamiliar code it touches ([#261](https://github.com/ltowarek/dust-mite/issues/261)) |

**CI on agent drafts.** Project rules open every PR as a draft, and CI runs on drafts too ([AGENTS.md](../../AGENTS.md), changed in #255). An agent draft therefore arrives with CI results, as long as a workflow actually starts. A push or PR made with the default `GITHUB_TOKEN` [does not trigger workflows][gha]. So the run must push and open the PR with a token that does trigger them, such as a GitHub App token or the Claude app's own token. Otherwise CI never starts until the owner pushes. Test this at stage 1.

## 5. Recommendation

### Shortlist

- **A. `claude-code-action`, one ticket per run.** The deterministic shape Matt recommends and uses, on hardware CI already proves, free on a public repo, with the action's own rule against merging.
- **B. Cloud scheduled task.** The least setup and the clearest terms status, at the price of agent-driven picking, preview status and untested firmware builds. Keep as the comparison, not the first step.

Rejected: H and I fail the Pro constraint; F contradicts GitHub's public-repo guidance; G is an environment with no queue; C is parallel by design with no enforced cap; E adds a TypeScript dependency for what about 50 lines of YAML does at this scale. D is not on the shortlist because it stops when the PC does, but it appears as a stage.

### Run shape for A

```text
on: schedule (daily) | workflow_dispatch
concurrency: one group, timeout-minutes, --max-turns

deterministic YAML
  if any open agent PR awaiting review: exit        # WIP limit
  ticket = first open ready-for-agent
           with issue_dependencies_summary.blocked_by == 0
           and no needs-hardware label, no in-progress label, no PR targeting it
  if none: exit
  label in-progress; create branch from origin/main

agent step (anthropics/claude-code-action, plugin mattpocock-skills)
  prompt: /implement <ticket>, then write the PR body with /pr to a file
  on an undecided spec gap: comment and stop            # run never waits

deterministic YAML
  push branch; gh pr create --draft --body-file ...
  on failure: label agent-failed, comment reason, stop retrying this ticket
  always: remove in-progress
```

Install the skills with the action's [`plugins` input][gha] and [`mattpocock-skills@claude-plugins-official`][m-readme]. Released skills only, because the plugin [excludes `in-progress`][m-progress]. The repo has no `.claude/skills` today, so cloud and CI cannot see the local `~/.claude/skills`.

### Staged path

Each stage is usable alone. Advance when the previous one is boring.

| Stage | What changes | PC | What it teaches |
| --- | --- | --- | --- |
| 0. Tickets | `/triage` two or three small tickets, install `/pr`, run `/implement` interactively, note `/usage` per ticket | On | What an AFK-ready brief is; real cost of a ticket against the five-hour window, which no doc gives |
| 1. Mention | `@claude` on one ticket through the existing [`claude.yml`](../../.github/workflows/claude.yml), adding plugin, `--allowedTools` for `docker`, `--max-turns`, timeout | Off | What a disposable runner lacks; [no shell without grants][gha]; owner still clicks the PR link |
| 2. Button | `workflow_dispatch` with the deterministic picker and draft PR from the sketch above | Off | The orchestrator slot; label state machine; the factory's five questions (*beta* vocabulary only) |
| 3. Clock | Daily cron at a quiet hour, WIP limit of one, no retry beyond the next tick. [Schedule stops after 60 days without activity on public repos][gha] | Off | Throttles and brakes; shared-limit collisions with interactive work |
| 4. Second reader | One fresh-context pass of Matt's `code-review`, comment only, one fix round, then measure | Off | Whether automated review saves or costs human time |
| 5. Compare | Same prompt as a cloud scheduled task for a week, using `gh api` and built-in tools; then decide. Sandcastle only if YAML stops being enough | Off | What a vendor runner gives and takes away |

Hardware tickets stay out of the picker by label. The owner runs them in a normal session while PC and car are on; [Remote Control][rc] is available on Pro if a phone view helps.

### Guardrails from the first unattended run

- Anthropic's checklist: know what done looks like, can check its own work, limited scope, a cap on turns, and "have a person approve the result at the end" ([best practices][bp]).
- **Enforce the merge gate.** `Protect main` requires a PR and checks but [0 approvals and no bypass](#repo-facts-checked-today), so a token with write access and passing checks could merge. Requiring one approval would block a bot's own merge. Because [authors cannot approve their own PRs][gh-approve], it would also block the owner's self-authored PRs and cloud runs acting as the owner, so it needs a decision.
- Anthropic's harness post names two failure patterns, doing too much at once and declaring victory early, and asks for mergeable state at each session's end ([Nov 2025][harness]). One ticket per run answers the first; before and after evidence in `/pr` answers the second.
- **Prompt injection on a public repo.** The action checks [write access on triggers][a-sec] and warns of hidden markdown in untrusted content. A cron prompt that reads comments is still exposed; the same concern is open on [Sandcastle #1046][sc-1046]. Have the prompt read the brief and owner comments only. gh-aw's [integrity filter][aw-faq] is a model worth copying.
- Keep usage credits off, so a limit [rejects runs][routines] rather than spending money.

## 6. What the sources did not settle

1. **Terms.** Whether a recurring unattended loop on Pro is "explicitly permit[ted]" and "ordinary, individual usage". Only Anthropic can settle this. Enforcement thresholds are not published.
2. **Capacity.** No published figure for tickets per five hours or per week on Pro ([plan page][pro] gives limits but no numbers). Stage 0 measures it.
3. **Action at a usage limit.** No action-specific behaviour is documented. Generic docs say [`-p` returns non-zero][headless]. An open report says [a weekly limit can exit 1 without any stdout signal][bug-limit]. A second open report, on Max and unconfirmed, says [headless uses about 1.8× more of the window][bug-weight]. Both are user reports.
4. **`--bare` risk.** Docs say `--bare` "will become the default for `-p` in a future release" ([headless][headless]) and "does not read `CLAUDE_CODE_OAUTH_TOKEN`" ([auth][auth]). If both hold, subscription scripts may need an explicit opt-out. Whether the action is affected is unstated.
5. **`/implement` via a prompt.** It has `disable-model-invocation: true` ([skill][m-impl]). The action says `prompt` accepts a skill invocation ([docs][gha]), but `/loop` fires pass such skills [as plain text][sched]. Behaviour in action and cloud prompts for this flag is not stated. Test at stage 1; fall back to a prompt that names the same steps.
6. **Cloud feasibility for this repo.** Untested: a 6.7 GB pull inside the roughly 5-minute setup window, an ESP-IDF build under [command timeouts][cloud], and whether the GHCR image is public (the local token lacks `read:packages`). The base image [cannot be replaced][cloud].
7. **Scheduled-task details.** Overlap handling, and whether a run can merge, are undocumented.
8. **Workflow-file edits.** The action FAQ says the app ["doesn't have workflow write access"][a-faq]; the docs' permission table lists [Workflows read and write][gha]. They conflict. It matters for infrastructure tickets. Test it.
9. **CI on agent drafts.** Which token the run pushes with, so that CI starts on its draft (section 4).
10. **Review evidence.** No controlled study found for `/pr`-style summaries, door or blast-radius labels, or stacked PR review time for a solo reviewer. Most data comes from teams.
11. **Sources not read.** `aihero.dev/workshops/afk-agents` returned 404. The Day 5 workshop and the AI Engineer talk were seen only through search results. Matt's `software-factory` daemon is unavailable. The Codex page stated no plan, trigger or Docker details. Conductor's page does not state how it logs in.
12. **Not re-verified.** Cezar's reset-aware start and OpenHands Agent Canvas's Pro login come from earlier notes; only cezar's README was reread here, and it did not mention the reset behaviour or Actions. The chat-app Projects feature was not examined, and "GitHub workspaces" was read as Codespaces.
13. **Copilot plans.** GitHub's plans page [contradicts itself][cp-plans] on third-party agents for Pro. Not material, since H is rejected.

## Repo facts checked today

From `gh` against `ltowarek/dust-mite` on 2026-11-05: public; 41 open issues, 0 labelled `ready-for-agent` or `ready-for-human`; one open PR; ruleset `Protect main` has `pull_request` with 0 required approvals, 7 required status checks, and no bypass actors; `.github/` has no PR template; `gh api repos/ltowarek/dust-mite/issues/197` returns `issue_dependencies_summary.blocked_by: 0, total_blocked_by: 1`, confirming that closed blockers drop out of the open count.

<!-- Link definitions -->

[m-readme]: https://github.com/mattpocock/skills/blob/main/README.md
[m-pr]: https://github.com/mattpocock/skills/blob/main/skills/engineering/pr/SKILL.md
[m-pr-doc]: https://github.com/mattpocock/skills/blob/main/docs/engineering/pr.md
[m-pr-credits]: https://github.com/mattpocock/skills/blob/main/skills/engineering/pr/CREDITS.md
[m-impl]: https://github.com/mattpocock/skills/blob/main/skills/engineering/implement/SKILL.md
[m-impl-doc]: https://github.com/mattpocock/skills/blob/main/docs/engineering/implement.md
[m-spec-doc]: https://github.com/mattpocock/skills/blob/main/docs/engineering/implement-spec.md
[m-triage-doc]: https://github.com/mattpocock/skills/blob/main/docs/engineering/triage.md
[m-brief]: https://github.com/mattpocock/skills/blob/main/skills/engineering/triage/AGENT-BRIEF.md
[m-tracker]: https://github.com/mattpocock/skills/blob/main/skills/engineering/setup-matt-pocock-skills/issue-tracker-github.md
[m-progress]: https://github.com/mattpocock/skills/blob/main/skills/in-progress/README.md
[m-sf]: https://github.com/mattpocock/skills/blob/main/skills/in-progress/software-factory/SKILL.md
[m-sf-run]: https://github.com/mattpocock/skills/blob/main/skills/in-progress/software-factory/RUNNERS.md
[m-tips]: https://www.aihero.dev/tips-for-ai-coding-with-ralph-wiggum
[m-ralph]: https://www.aihero.dev/getting-started-with-ralph
[ralph]: https://ghuntley.com/ralph/
[sc-readme]: https://github.com/mattpocock/sandcastle/blob/main/README.md
[sc-start]: https://github.com/mattpocock/sandcastle/blob/main/docs/guide/getting-started.md
[sc-seq]: https://github.com/mattpocock/sandcastle/blob/main/src/templates/sequential-reviewer/implement-prompt.md
[sc-seq-main]: https://github.com/mattpocock/sandcastle/blob/main/src/templates/sequential-reviewer/main.mts
[sc-retry]: https://github.com/mattpocock/sandcastle/blob/main/.out-of-scope/provider-error-retry.md
[sc-wf]: https://github.com/mattpocock/sandcastle/blob/main/.github/workflows/agent-implement.yml
[sc-impl]: https://github.com/mattpocock/sandcastle/blob/main/.sandcastle/agent-workflows/implement/implement.ts
[sc-daemon]: https://github.com/mattpocock/sandcastle/blob/main/.factory/run-daemon.sh
[sc-1046]: https://github.com/mattpocock/sandcastle/issues/1046
[terms]: https://www.anthropic.com/legal/consumer-terms
[aup]: https://www.anthropic.com/legal/aup
[legal]: https://code.claude.com/docs/en/legal-and-compliance
[auth]: https://code.claude.com/docs/en/authentication
[sdk-plan]: https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan
[pro]: https://support.claude.com/en/articles/8325606-what-is-the-pro-plan
[gha]: https://code.claude.com/docs/en/github-actions
[a-faq]: https://github.com/anthropics/claude-code-action/blob/main/docs/faq.md
[a-sec]: https://github.com/anthropics/claude-code-action/blob/main/docs/security.md
[routines]: https://code.claude.com/docs/en/routines
[cloud]: https://code.claude.com/docs/en/cloud-environments
[web]: https://code.claude.com/docs/en/claude-code-on-the-web
[projects]: https://code.claude.com/docs/en/claude-projects
[features]: https://code.claude.com/docs/en/feature-availability
[m-guard]: https://github.com/mattpocock/skills/blob/main/skills/misc/git-guardrails-claude-code/SKILL.md
[interactive]: https://code.claude.com/docs/en/interactive-mode
[selfhost]: https://code.claude.com/docs/en/self-hosted-environments
[harness]: https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
[skills]: https://code.claude.com/docs/en/skills
[headless]: https://code.claude.com/docs/en/headless
[workflows]: https://code.claude.com/docs/en/workflows
[teams]: https://code.claude.com/docs/en/agent-teams
[sched]: https://code.claude.com/docs/en/scheduled-tasks
[goal]: https://code.claude.com/docs/en/goal
[rc]: https://code.claude.com/docs/en/remote-control
[agent-view]: https://code.claude.com/docs/en/agent-view
[bp]: https://code.claude.com/docs/en/best-practices
[cr-docs]: https://code.claude.com/docs/en/code-review
[cr-post]: https://claude.com/resources/articles/code-review
[cc-review]: https://claude.dev/blog/solving-code-review-at-anthropic/
[bug-limit]: https://github.com/anthropics/claude-code/issues/103820
[bug-weight]: https://github.com/anthropics/claude-code/issues/97074
[runner]: https://docs.github.com/en/actions/reference/runners/github-hosted-runners
[limits]: https://docs.github.com/en/actions/reference/limits
[conc]: https://docs.github.com/en/actions/concepts/workflows-and-actions/concurrency
[billing]: https://docs.github.com/en/billing/concepts/product-billing/github-actions
[gh-sec]: https://docs.github.com/en/actions/reference/security/secure-use
[cs-billing]: https://docs.github.com/en/billing/concepts/product-billing/github-codespaces
[cs-dev]: https://docs.github.com/en/codespaces/setting-up-your-project-for-codespaces/adding-a-dev-container-configuration/introduction-to-dev-containers
[deps]: https://docs.github.com/en/rest/issues/issue-dependencies
[gh-approve]: https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/reviewing-changes-in-pull-requests/approving-a-pull-request-with-required-reviews
[cs-idle]: https://docs.github.com/en/codespaces/setting-your-user-preferences/setting-your-timeout-period-for-github-codespaces
[cp-third]: https://docs.github.com/en/copilot/concepts/agents/about-third-party-agents
[cp-agent]: https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent
[cp-plans]: https://github.com/features/copilot/plans
[aw-claude]: https://github.github.com/gh-aw/engines/claude/
[aw-safe]: https://github.github.com/gh-aw/reference/safe-outputs-pull-requests/
[aw-faq]: https://github.github.com/gh-aw/reference/faq/
[stack]: https://github.blog/changelog/2026-07-30-stacked-pull-requests-are-now-in-public-preview/
[stack-doc]: https://github.com/github/docs/blob/main/content/pull-requests/tutorials/roll-out-stacked-prs.md
[stack-bug]: https://github.com/github/gh-stack/issues/323
[gastown]: https://github.com/gastownhall/gastown
[conductor]: https://www.conductor.build/
[vk]: https://github.com/BloopAI/vibe-kanban
[vk-end]: https://www.vibekanban.com/blog/shutdown
[cu]: https://github.com/dagger/container-use
[symphony]: https://github.com/openai/symphony
[codex]: https://learn.chatgpt.com/docs/cloud
[cursor]: https://cursor.com/docs/cloud-agent
[hive]: https://github.com/link-assistant/hive-mind
[cezar]: https://github.com/open-mercato/cezar
[dora-batch]: https://dora.dev/capabilities/working-in-small-batches/
[dora-wip]: https://dora.dev/capabilities/wip-limits/
[dora-2025]: https://cloud.google.com/blog/products/ai-machine-learning/announcing-the-2025-dora-report
[pr-fail]: https://arxiv.org/abs/2601.15195
[pr-task]: https://arxiv.org/abs/2602.08915
[smartbear]: https://smartbear.com/learn/code-review/best-practices-for-peer-code-review/
[fregnan]: https://arxiv.org/abs/2208.04259
[cihan]: https://arxiv.org/abs/2412.18531
[meta]: https://engineering.fb.com/2022/11/16/culture/meta-code-review-time-improving/
