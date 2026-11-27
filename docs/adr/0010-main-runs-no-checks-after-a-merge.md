# A push to `main` runs no checks, only publish work

Every push to `main` reran all of CI: each area's linters, formatters, type checks and clang-tidy, the AFK workflow tests against the canary ticket and the canary PR, and the tests, all of which had already run on the pull request. Only part of that run did anything that a pull request cannot do: publishing the GHCR images, writing the devcontainer `buildcache` tags and the Docker build cache, and uploading `main`'s Codecov reference data. The rest spent runner minutes and the Claude subscription's limits on confirming again what the pull request had proved ([#403](https://github.com/ltowarek/dust-mite/issues/403)).

A pull request therefore runs every check and every test, and a push to `main` runs only publish work: the GHCR image publish, every devcontainer image build with its cache write, and every area's tests workflow, whose Codecov uploads are the reference that pull request comparisons use as their base. Each trigger has its own entry workflow, `CI` on pull requests and `Publish` on pushes to `main`. `CI` calls `Publish` as a dry run, with the production image publish and the cache writes off, so every pull request runs the workflow that a push to `main` runs.

The `main` ruleset does not require branches to be up to date before merging, and `main` accepts only squash merges. The squash commit on `main` is therefore a commit that no check ran on: two pull requests that each pass against an older `main` can together break the checks on `main`, and no run reports it. This risk is accepted in exchange for the runner minutes and subscription limits that the push run no longer spends; the tests on `main` still run.

## Considered Options

- **Keep one entry workflow on both triggers.** Rejected: every reusable workflow then reads the triggering event, or `if:` conditions choose its jobs, so trigger knowledge spreads into every area.
- **Run the checks on `main` as well.** Rejected: it spends runner minutes, and the AFK workflow tests spend the Claude subscription's limits, on what the pull request has already checked.
- **Require up-to-date branches or a merge queue.** Deferred: either one tests the commit that lands, but every merge then waits for a rerun of CI on the updated branch.

## Consequences

- A broken `main` shows only through a failing tests job in `Publish` or through the next pull request's checks.
- If a broken `main` occurs, requiring branches to be up to date in the `main` ruleset is the way out: each pull request's checks then run on the commit that lands.
- A new job belongs in an area's tests workflow when it runs tests, and otherwise in the area's checks workflow; the push run picks it up or skips it without further edits.
