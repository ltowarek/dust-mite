# Workflow actions are locked in GitHub's workflow dependency lockfile

Every workflow referenced its actions by a moving tag such as `actions/checkout@v4`. An action's owner can move a tag to new code at any time, and the workflows then run that code with their tokens and secrets without any change in this repository ([#213](https://github.com/ltowarek/dust-mite/issues/213)).

Every workflow is therefore onboarded to GitHub's [workflow dependency lockfile](https://docs.github.com/en/actions/concepts/security/workflow-dependency-lockfiles), [.github/workflows/actions.lock](../../.github/workflows/actions.lock), which GitHub's secure-use reference names as the measure that supersedes SHA pinning. The lockfile records the commit, owner and repository of every action, including the transitive dependencies of composite actions. The `uses:` lines keep full version tags, such as `actions/checkout@v4.4.0`, so each line names exactly one commit and remains readable. The [`github/gh-actions-lock`](https://github.com/github/gh-actions-lock) extension generates the lockfile, and the `ci-status-actions-lock` check verifies it on every pull request and push to `main`.

The extension warns that the container image of the CI jobs, `${{ needs.build-docker.outputs.image }}`, is chosen at runtime and cannot be checked. That expression resolves to the run's own devcontainer image, pinned by digest ([ADR 0004](0004-ci-jobs-pin-devcontainer-image-by-digest.md)), and the extension cannot follow job outputs ([github/gh-actions-lock#236](https://github.com/github/gh-actions-lock/issues/236)). The warning does not fail verification, and it stays visible and unsuppressed.

## Considered Options

- **SHA pins with version comments in `uses:`.** Rejected: the version survives only in a comment that nothing checks, and the dependencies of a composite action stay on whatever references its owner chose.
- **Floating tags, as before.** Rejected: an action's owner can move a tag to new code without any change in this repository.

## Consequences

- A change to a `uses:` line, or a new workflow, must regenerate the lockfile with [scripts/lock_github_actions.sh](../../scripts/lock_github_actions.sh), or verification fails.
- The script pins the extension's version, and that version is bumped by hand, because no Dependabot ecosystem covers `gh` extensions.
- The container-image warning appears on every verification until the extension can follow job outputs.
