# Maintainer coding rules not yet stated in the dust-mite repository

Question: which of the maintainer's coding rules are absent from the repository, so that an agent that sees only the repository would not know them?

Sources:

- The rules: the maintainer's local agent memory on 2026-11-06, after that day's cleanup. It has 25 `feedback_*` files, plus project and user notes that were skimmed for coding rules embedded in them. The rules below are paraphrased in neutral wording.
- The cleanup: on 2026-11-06 the maintainer deleted 26 memories. Some held rules that the repository already states in full; the rest were project notes about finished work. Rules that came only from deleted memories are listed in section 4 and are not analysed further.
- The repository: `origin/main` at `8b95156`, fetched on 2026-11-06. This is the tree that a fresh runner checks out. `CLAUDE.md` is a symlink to `AGENTS.md`. Every `file:line` below refers to that commit.

## 1. Summary

- 10 dust-mite code rules in memory are stated partly or not at all in the repository (section 2). 2 are mechanical, 2 are mixed (a mechanical proxy for a judgement rule), and 6 are judgement calls. None has an enforcing tool that is already active.
- 5 code rules are fully stated in the repository (section 3). Their memory notes were deleted, so the repository is now their only source.
- The rules most likely to cause a review argument are all about test shape or code shape, and the code already follows them without the repository saying so: one assertion per test, and single-use constants kept local.

## 2. dust-mite code rules not fully stated in the repository

| # | Rule | Repo status | Mechanical or judgement | Enforcing tool and rule ID |
|---|---|---|---|---|
| 1 | A test checks one thing. Several input-to-output cases become a parametrized test with a named id per case (`pytest.param(..., id=...)`, Vitest `test.each`). A test that checks two consequences of one action is split in two. | Not stated. The code follows it, for example `pytest.param(` in `controller/tests/unit/controller/test_input_backends.py` and `test.each` at `web/tests/unit/input.test.js:100`, but no document requires it. | Mixed. Two assertions on facets of one object are a judgement call. | Vitest: oxlint `vitest/max-expects`, option `max` (default 5), Style category. It needs `"plugins": [..., "vitest"]` in `web/.oxlintrc.json`. Setting `plugins` overwrites oxlint's default set (`eslint`, `typescript`, `unicorn`, `oxc`), so the list must include those again. Today the config enables only the `correctness` and `suspicious` categories (`web/.oxlintrc.json:4-7`). Python: ruff `PT018` (composite assertion) splits only `assert a and b` and is already selected by `ALL` (`controller/pyproject.toml:62`). No pytest or ruff rule that caps the number of asserts per test was found. |
| 2 | A constant used by one test or function is declared inside it. Module level is only for values that two or more functions share. | Not stated. | Mechanical: count the references within the module. | None found. Ruff `PLR2004` (magic-value comparison) is active and pushes toward named values, but it does not decide where they live. |
| 3 | Domain functions neither take nor return OpenTelemetry objects (`Context`, spans). Only the tracing adapter (`controller/src/controller/tracing.py`, and the C++ tracing component) exposes them. The caller that opens the span calls the extraction helper itself. | Not stated. `CONTRIBUTING.md:326-330` shows extraction at the site that opens the span, as an example only. | Judgement | None workable. Ruff `TID251` (`lint.flake8-tidy-imports.banned-api`) could ban the `opentelemetry` names, but it would need a per-file exemption for `tracing.py`, which `CONTRIBUTING.md:13` forbids. It would also flag modules that legitimately use `trace` (`CONTRIBUTING.md:317`). |
| 4 | Design as a functional core and an imperative shell. Decisions live in pure functions with unit tests. The shell (sockets, loops, signals, threads) gets a few integration tests against in-process or local replacements. A few end-to-end tests cover the happy path. Do not propose mid-level seams with test doubles. | Partly. `CONTRIBUTING.md:11` covers the no-mocks half. `CONTRIBUTING.md:607-611` lists test types but gives no design rule and no proportions. | Judgement | None found |
| 5 | Do not add a class or dataclass whose only content is one field just to hold state, for example to avoid a `global` statement. Restructure so that the real object is the module-level state. | Not stated. `CONTRIBUTING.md:13` forbids silencing findings, but such a wrapper dodges the finding without silencing it. | Judgement | None found. Ruff `PLW0603` (global statement) is active and is the finding these wrappers dodge. |
| 6 | A loop that increments a counter on every iteration is a `for` loop with an `int` counter in the init clause, `for (int i = 0;; ++i)` when it is unbounded. `while` is only for loops without a counter. | Not stated | Judgement: it needs data flow. | None found. The clang-tidy check list has `modernize-loop-convert`, `bugprone-too-small-loop-variable` and `bugprone-float-loop-counter`, and none of them encodes this rule. clang-tidy findings cannot block CI anyway: `WarningsAsErrors: ''` (`car/.clang-tidy:22-24`). |
| 7 | Prefer the plain, vendor-maintained setup to clever tricks or self-maintained copies of a vendor's setup, even when the trick saves size or time. "A reader needs an explanation" and "we maintain a copy" count as costs. | Partly. `CONTRIBUTING.md:4` prioritises "technical clarity, learning value, and iteration speed". `README.md:17` asks for "a practical architecture that is straightforward to extend". | Judgement | None found |
| 8 | Pin each development tool's version in one place (a devcontainer `FROM` or build `ARG`, requirements, or `package.json`) so that Dependabot bumps one place. Do not adopt the pre-commit framework, whose hook `rev:` duplicates the pin. | Partly. `CONTRIBUTING.md:64-66` describes the repository's own hook delegating to per-container scripts. `CONTRIBUTING.md:1097` pins the infrastructure tools by build arguments. Neither states the rule. | Mixed: the absence of `.pre-commit-config.yaml` is mechanical, the single pin is judgement. | None found. A CI step could test that the file is absent. |
| 9 | Helpers under `scripts/` are bare command sequences: no error handling, no usage or help text, and no argument parsing beyond passing `"$@"` through. Names are specific, for example `lock_github_actions.sh`, not `lock_actions.sh`. | Not stated. `CONTRIBUTING.md:583` says only "repository-level helper scripts". In-tree precedent is mixed: `scripts/optimize_image.sh:38-40` branches and exits with an error message. | Judgement | None found. ShellCheck and shfmt (`CONTRIBUTING.md:1073`) do not check this. A grep for `getopts` or `usage` would only be a proxy. |
| 10 | The `devices:` passthrough in the devcontainer compose files stays commented out in commits. Uncomment it locally only. | Partly. `CONTRIBUTING.md:112` says to "manually uncomment the `devices:` entries" but does not forbid committing them. Both files currently hold `# devices:` (`.devcontainer/cpp/docker-compose.yml:19`, `.devcontainer/python/docker-compose.yml:20`). | Mechanical | None found. yamllint cannot check this. A CI grep could. |

All 10 come from feedback files.

## 3. Rules fully stated in the repository

Their memory notes were deleted on 2026-11-06, so these rules now come only from the repository.

- Test doubles: no mocks or monkeypatching, hand-written doubles only, and inject the collaborator, setting or environment mapping (`CONTRIBUTING.md:11`, `CONTRIBUTING.md:17-38`). The repository bans pytest `monkeypatch` entirely (`CONTRIBUTING.md:35`). The deleted memory note allowed `monkeypatch.setenv`, so the repository's ban now holds. `CONTRIBUTING.md:38` says that no linter enforces these rules. Two options were verified, but neither is configured:
  - Ruff `TID251` with `lint.flake8-tidy-imports.banned-api` can ban `unittest.mock`.
  - pytest `addopts = -p no:monkeypatch` disables the fixture. `monkeypatch` is a default pytest plugin, not an essential one, so blocking it is allowed.

  No oxlint rule was verified that bans `vi.mock` or `vi.spyOn` while keeping `vi.useFakeTimers`.
- A test takes its expected values from outside the code under test: a literal, or a named constant from a library or a standard (`CONTRIBUTING.md:12`).
- Linter, formatter and type-checker findings are fixed, not suppressed. The one exception is a single reasoned suppression for an interface outside the repository (`CONTRIBUTING.md:13-14`, `AGENTS.md:68`). Some partial tooling exists: `strict = true` (`controller/pyproject.toml:42`) enables mypy's `--warn-unused-ignores`. mypy's `ignore-without-code` error code exists but is not enabled (`controller/pyproject.toml:43` enables only `explicit-override`).
- Comments and docstrings are terse, one line by default, and each reason lives in one place (`AGENTS.md:69`).
- Optional firmware features are Kconfig `default n` flags. Each is set in a `car/sdkconfig.defaults.<overlay>` that CI builds (`CONTRIBUTING.md:1024-1038`).

## 4. Rules dropped with their memories

These were in memory only, and the maintainer deleted the notes that held them on 2026-11-06. No source states them now.

- Two refinements of the expected-values rule: no test that pins a library enum's numeric value, and no examples from current code in documentation rules.
- Refinements of the terse-comment rule: an ordering rule goes at the call site, a well-named call gets no comment, and a test docstring is one sentence plus at most a one-line prerequisite.
- Use a library's public API, never its private attributes. Ruff `SLF001` still enforces this for Python, because `ALL` selects it (`controller/pyproject.toml:62`).
- Name things with established industry terms in preference to repository-only coinages.
- In tests, close synchronous WebSocket connections on another thread with a bounded join.
- Fix the root cause before adding a local or client-side workaround.
- Install infrastructure devcontainer tools from their GitHub releases by build `ARG`, and keep `gh` out of the images.
- One ticket becomes one stacked draft pull request.
- Reuse a standard-library or installed-library parser, such as `http.client.parse_headers` or `urllib.parse`, instead of hand-written tokenising. `AGENTS.md:66` still asks for the standard library's idiomatic form in general.
- In ESP-IDF, a readiness wait is owned by the component that owns the state, backed by an event-group bit it sets from its own event handlers, as the IDF examples do. `AGENTS.md:66` still asks for the library's idiomatic form in general.

## 5. Behavioural rules

- Always pass `--env-file .env` to a devcontainer or build container. Stated for the command (`AGENTS.md:89`). The reason, that firmware compiles the Wi-Fi credentials in at configure time, is not stated.
- Run toolchain commands inside the devcontainer, never on the host. Fully stated (`AGENTS.md:62-63`); its memory note was deleted.
- Install nothing on the host. `gh` and its extensions are the exception. Fully stated (`AGENTS.md:62`); its memory note was deleted.
- After a push, do not watch or poll CI unless the request asks for it. Not stated.
- Do not run the car pre-commit check locally after a firmware change, because CI runs it. Not stated, and it conflicts with `CONTRIBUTING.md:1141` ("run the relevant local checks").
- Commit locally and wait for the owner's review before pushing. The same applies to issues, issue edits, comments and labels. Partly stated: `AGENTS.md:73` requires draft pull requests.
- Agents never merge, and the owner reviews every pull request. Prefer workflow changes the owner can follow in stages to the fastest route to autonomy. Not stated. `CONTRIBUTING.md:1176` covers auto-merge for Dependabot only.
- Start each ticket on a new branch from a freshly fetched `origin/main`. Not stated. The companion rule, to ask about a spec gap at once and amend the spec afterwards, is fully stated (`AGENTS.md:71`).
- Recommend or build on only the released skills of the external skills collection that `docs/agents/triage-labels.md` names, never its in-progress ones. Not stated.
- Operational notes for hardware verification: the car pre-commit script prints nothing on success; `idf.py clang-check` switches the build directory to the clang toolchain; check swap as well as free memory before a build. Partly stated (`AGENTS.md:74` covers `free -h` only).
- One build at a time. Fully stated (`AGENTS.md:74`).
- Use a compose project name unique to the session, and one worktree per ticket, because parallel agent sessions share `-p dust-mite-agent`. Not stated, and it conflicts with the example at `AGENTS.md:104`.

## 6. Rules for other repositories

These are not analysed further.

- Verify fork builds from an isolated source snapshot, never from the shared submodule checkout (opentelemetry-cpp fork).
- In the esp-opentelemetry-cpp library, comments give only the reason, never mention downstream projects, and big lambdas become named functions.
- Commits and pull request drafts bound for the opentelemetry-cpp upstream carry no AI attribution trailer.
- A small dependency-configuration fix in esp-opentelemetry-cpp ships without a new regression test app unless the owner asks for one.
- Never open a pull request against a third-party upstream. Prepare the branch and the text, and hand them over.
- In fork branches, extract duplicated logic into a shared internal helper as a refactor commit, followed by the change, in one pull request. `AGENTS.md:66` already states the commit-order part for dust-mite.
- From project notes, all for the forks:
  - In opentelemetry-cpp tests, readable repetition is preferred to case tables or combinatorial parameters.
  - In esp-opentelemetry-cpp, use `std::atomic` instead of `volatile` with assembly barriers.
  - In esp-opentelemetry-cpp, each signal's endpoint is configured separately, with no fallback that reuses another signal's URL.
  - In opentelemetry-cpp, clang-format's alignment is accepted; never write `// clang-format off`.

## 7. What could not be settled

- **Snapshot:** the assessment uses `origin/main` at `8b95156`. Anything merged after it was not seen.
- **Local pre-commit:** the memory says to leave the car pre-commit check to CI. `CONTRIBUTING.md:1141` says to run local checks before opening a pull request. The two disagree.
- **Containers and worktrees:** the memory says to use one worktree per ticket and a compose project name unique to the session. `AGENTS.md:104` shows one shared `-p dust-mite-agent` project for agent runs. Which one holds is unclear.
- **Scope of origin:** the `for`-loop rule (row 6) and the shared-helper rule (section 6) both arose in fork work. Row 6 is worded for any counter loop, so it is listed as a dust-mite rule. Whether either binds dust-mite firmware was not confirmed.
- **Rule IDs not fully verified:**
  - The ruff documentation pages fetched do not state whether `PT018`, `PLR2004`, `PLW0603` and `TID251` are stable or preview rules. Each page gives only the version that added the rule.
  - Whether `select = ["ALL"]` picks up preview rules without `preview = true` was only inferred from the settings page.
  - No oxlint rule that bans specific `vi.*` members was verified.
  - "None found" for clang-tidy rests on check names in the published list, not on each check's documentation.
