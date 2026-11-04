# CI jobs run in their own run's devcontainer image, pinned by digest

The Python controller, C++ car and JavaScript web workflows built their devcontainer image, pushed it to one shared `latest` tag in GHCR, and ran their check jobs in the image pulled from that tag. When two runs overlapped, a job could run in the image that the other run had pushed. Run [41141975220](https://github.com/ltowarek/dust-mite/actions/runs/41141975220) for [#206](https://github.com/ltowarek/dust-mite/pull/206) failed its type checks this way: the run for [#210](https://github.com/ltowarek/dust-mite/pull/210) pushed its own image, without `aiohttp`, to the shared tag 8 s after the run for #206 pushed its image ([#211](https://github.com/ltowarek/dust-mite/issues/211)).

Each run therefore builds its devcontainer image once, in the reusable workflow `devcontainer-image.yml`, and runs every container job in exactly that image, pinned by digest. A digest is content-addressed, so no push by another run can change the image that a job runs. The jobs keep GitHub's native `container:` support, so each check stays its own job with its own logged steps.

Without a layer cache, the C++ car workflow spent 7–8 minutes rebuilding its devcontainer image on every run. The image builds therefore share a layer cache in GHCR. Only builds on `main` write it, so one pull request's Dockerfile experiment cannot change the cache that every other run reads.

## Considered Options

- **`devcontainers/ci`.** Rejected: Compose-based devcontainers, which all three are, are not documented as supported; every job would build its own copy of the image; and each job's checks would collapse into one `runCmd` step.
- **Artifact transfer.** Rejected: a container job pulls its image before any step runs, so no step can load an artifact into it.
- **Building and running the image in each job.** Rejected: every job rebuilds the image, and the C++ car workflow runs 13 jobs per run in a 6.7 GB image.
- **Inline cache.** Rejected: it supports only `min` mode, which does not cache the QEMU builder stage of the C++ image.
- **The GitHub Actions cache backend.** Rejected: the repository's Actions cache already held 10.5 GB against its 10 GB limit, so a layer cache there would push out the ccache entries of the C++ car workflow.
- **Deleting old images.** Rejected: keeping them costs nothing, and every way of deleting them costs something. The devcontainer packages are public, so GitHub bills neither their storage nor their data transfer, and a run whose layers come from the cache adds only its manifests. GHCR has no built-in retention policy, so deletion would need a workflow with delete rights over the packages. Each image is an OCI index that includes a provenance attestation, so a cleanup that deletes untagged versions also deletes parts of tagged images. Deleting a run's image when the run ends would break "Re-run failed jobs", which runs the failed jobs in the image that the earlier attempt built.

## Consequences

- Every run adds an image to GHCR, and no workflow deletes it.
- No tag points at the current image. The `latest` tag in each devcontainer package predates this decision, and no workflow updates or reads it.
