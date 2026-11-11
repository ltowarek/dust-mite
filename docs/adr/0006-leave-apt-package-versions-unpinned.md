# Leave apt package versions unpinned

hadolint's rule [DL3008](https://github.com/hadolint/hadolint/wiki/DL3008) asks every `apt-get install` to pin each package to an exact version, such as `curl=<version>`. The Debian and Ubuntu mirrors keep only the current version of each package in a release. A security update replaces the pinned version on the mirror, so a pinned `apt-get install` stops finding it, and the image build fails without any change in this repository. No Dependabot ecosystem updates apt pins, so every such failure would need a manual update ([#237](https://github.com/ltowarek/dust-mite/issues/237)).

The Dockerfiles therefore install apt packages without versions. Each build takes the current version from the base image's release, and the base image's tag or digest fixes that release. The hadolint configuration in [.hadolint.yaml](../../.hadolint.yaml) ignores DL3008, and nothing else. It is the only rule ignored for the whole repository that the ground rules in [CONTRIBUTING.md](../../CONTRIBUTING.md#ground-rules) permit.

## Considered Options

- **A pin on every package.** Rejected: each pin breaks the build when the mirror drops the pinned version, which happens with every security update to that package, and no tool updates the pins.
- **A `snapshot.debian.org` date pin.** Rejected: it fixes every package to one date, but the images then miss security updates until the date is moved by hand. The snapshot service is also slower and less available than the regular mirrors.

## Consequences

- Two builds of the same Dockerfile can install different patch versions of a package.
- The base image tag or digest remains the only pin on the apt packages of an image.
- A new Dockerfile needs no apt version pins, and hadolint does not ask for them.
