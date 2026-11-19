# Workflows and scripts stay thin; complex automation logic lives in tested Python

The repository's automation is bash: inline `run:` blocks in the CI workflows, and `.sh` scripts. No test exercises it. The AFK workflows decide the most: `afk-run.yml` has 502 lines and 21 `if:` lines, `afk-update-branch.yml` 381 and 19, and `afk-run-pr.yml` 401 and 12. They decide which ticket a run works on, whether to refuse or queue it, what to push, which labels to move and what each comment says. A workflow started by an event other than a pull request runs from `main`, so a change to it first runs after it merges, and the only check before merge is static ([#331](https://github.com/ltowarek/dust-mite/issues/331)).

A workflow step or a script therefore stays bash, or YAML, only while it runs tools in sequence. It is too complex once it decides something, branching or looping on data it reads such as an API response, a ticket's shape or an agent's output, or once it passes about 100 lines. The [Google Shell Style Guide](https://google.github.io/styleguide/shellguide.html) draws the same line. A loop over a fixed list of commands is not a decision. Logic that is too complex moves into Python and gets tests, in the area that owns it. Repository tooling, which no runtime area owns, goes in `tools/<name>/`: one project per folder, in whatever language it needs, with its own toolchain files and tests. `scripts/` keeps the thin entry points that call those projects. Existing scripts move when a ticket changes them and they cross the line, not in one rewrite.

Scripts in `scripts/wizards/`, which the `/wizard` skill generates, are exempt. Their library half is identical in every wizard and must not be hand-edited, and each one runs once, interactively, with the maintainer watching.

A workflow keeps only what only GitHub can do: triggers, `needs`, permissions, timeouts, checkout, token minting, and steps that call one tool. Its complex logic moves into a Python project under `tools/`, run by composite actions in `.github/actions/` that are loaded with the `$/` self-repository syntax and import the project from the same commit. `$/` loads the code at the workflow's own commit and needs no checkout ([workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)). A host script that needs the same logic, such as a car agent session's desk script, imports the same package.

Only an entry workflow reads the triggering event. An entry workflow has one job, which passes the event's fields as inputs to one action or one reusable workflow. Every other workflow, action and package reads only its inputs, so a test can call it with the inputs an entry workflow would pass. A workflow started by `workflow_dispatch` needs no entry workflow, because `inputs` is its whole event.

Inside a package:

- **A pure core decides.** It returns its step outputs and its writes as data, called effects.
- **A thin shell does the rest.** It reads GitHub, runs the core, and carries out the effects with `gh` subcommands, using `gh api` only where `gh` has no subcommand.
- **Values arrive as inputs.** Workflows pass them as inputs and environment variables, and the package reads nothing from `github.event` or `$GITHUB_EVENT_PATH`.

Each action that writes, and each workflow that runs such an action, takes a `dry-run` input. In a dry run the shell records each effect as JSON in an `effects` output and calls neither `gh` nor `git` for it. Every read, token mint and output stays real.

The project is linted and tested in its owning area's devcontainer and CI area, with the checks of the repository's other Python areas: ruff with every rule, ruff format, mypy in strict mode, pytest through tox, and `pip-compile-multi verify`. It targets the oldest Python it runs on. Its logic is tested at three levels:

- **Unit tests.** They cover every decision of the core. One table-driven test maps each effect to its exact `gh` or `git` command through a hand-written spy, and one test guards that a dry run calls neither.
- **Action tests on GitHub.** The owning CI area, which the `ci.yml` entry workflow calls and the required `ci-status` check gates, runs each action on GitHub under its production job's permissions and tokens. Reads come from real, closed tickets, and writes run as dry runs.
- **Workflow tests on GitHub.** The same area runs every workflow that runs one of these actions, except entry workflows, through `workflow_call`, as a dry run, so the pull request's own copy is tested before merge. An entry workflow gets no workflow test: unit tests and action tests cover the action it calls, and only its mapping from event fields to inputs is left to static checks.

CI therefore writes nothing to the issue tracker and sends no notifications. The write calls themselves are covered only by the effect-to-command test and by real use after merge.

## Considered Options

- **Bash in `.sh` files, tested with bats and a fake `gh` on `PATH`.** Rejected: the style guide limits shell to small utilities without complex control flow, and a fake `gh` must reproduce `gh`'s output for every call the scripts make.
- **Inline bash in composite actions, tested only by workflow runs.** Rejected: the logic stays untestable outside GitHub.
- **JavaScript actions, the only kind with first-party test tooling.** Rejected: they bring a Node toolchain to the tooling and, once an action has a dependency, a committed `dist/` bundle that every change must rebuild.
- **A Go binary, built and cached per commit.** Rejected: it adds a toolchain, a build step and a cache to every job that runs it.
- **Python with githubkit or PyGithub instead of `gh`.** Rejected: both need a `pip install` in every job. githubkit 0.17.1 deprecates its httpx support, which its HTTP test fakes depend on, and its strict response validation rejected GitHub's own example payload. `gh` already absorbs the REST quirks the shell meets: URL-encoded label names, a 404 when removing an absent label, and GraphQL for ready-for-review.
- **Reading the triggering event from `github.event` or `$GITHUB_EVENT_PATH` wherever it is needed.** Rejected: a workflow started by `workflow_call` sees its caller's event, so the pre-merge workflow test would find nothing to work on, and every reader would need a fallback to inputs.
- **Testing entry workflows through `workflow_call`, with their event passed as inputs.** Rejected: an entry workflow would then need a second, reusable workflow to call, and the test would cover only the input mapping.
- **`act` or `wrkflw` for local workflow runs.** Rejected: both reject `$/` ([nektos/act#6189](https://github.com/nektos/act/issues/6189)), and neither runs GitHub's concurrency, permissions or App tokens.
- **A sandbox repository kept in sync with this one.** Rejected: the synchronization, a second App installation and the reporting back cost more than dry runs, which test this repository's own commit.
- **Fixture tickets created and closed by each test run.** Rejected: every fixture notifies the maintainer, and an App-applied AFK state on one could start a real AFK run.

## Consequences

- actionlint 1.7.12 rejects `$/` for actions ([rhysd/actionlint#711](https://github.com/rhysd/actionlint/issues/711)). Each workflow that calls an action with `$/` carries a per-file `ignore:` pattern in `.github/actionlint.yaml`, as the reusable workflow calls already do, and actionlint does not check inputs, outputs or permissions across those calls.
- Each workflow that has a workflow test also triggers on `workflow_call`, with its `dry-run` input and the outputs its test asserts on.
- The AFK workflows are the first to move ([#331](https://github.com/ltowarek/dust-mite/issues/331)). Their logic goes in `tools/afk/`, which the `infrastructure` area owns: its checks run in the infrastructure devcontainer, on that image's Python 3.11, and its GitHub tests run in `infrastructure.yml`. No other workflow has a `run:` block that decides anything. Of the 72 shell scripts, only the two `/wizard` scripts and `car/scripts/run_tests.sh` hold more than a sequence of commands; the wizards are exempt, and `run_tests.sh` loops over a fixed list.
- `afk-dispatch.yml` and `afk-promote-queued.yml` become entry workflows. The AFK workflow tests run `afk-run.yml` on the canary ticket, and `afk-run-pr.yml` and `afk-update-branch.yml` on the canary PR, whose numbers are in the `AFK_CANARY_TICKET` and `AFK_CANARY_PR` repository variables. Each runs a real agent on Haiku at `low` effort, so every CI run spends three agent sessions until CI runs areas only when their paths change ([#303](https://github.com/ltowarek/dust-mite/issues/303), [#225](https://github.com/ltowarek/dust-mite/issues/225)).
- The AFK App's private key and the Claude token are also Dependabot secrets; without them, every Dependabot pull request fails `ci-status`.
- The AFK publish phase refuses an agent's commit that changes any file under `.github/` or `tools/`, because the code there runs with the AFK App's write token in later runs, and the App's missing Workflows permission covers only `.github/workflows/`. User story 54 of [#309](https://github.com/ltowarek/dust-mite/issues/309) therefore stays true for the logic that leaves the workflows. A ticket that changes either directory is for a human.
