# AGENTS

This file is a lightweight navigation guide for coding agents.

- Source-of-truth guidance lives in existing project docs.
- This file intentionally avoids duplicating procedural details.
- `camera/` is intentionally omitted for now.

## Table of Contents

1. [Start Here](#start-here)
2. [Where to Find Things](#where-to-find-things)
3. [Working Rules for Agents](#working-rules-for-agents)
4. [Validation by Area](#validation-by-area)
5. [Docs and Generated Artifacts](#docs-and-generated-artifacts)

## Start Here

- Read [README.md](README.md) for project orientation and high-level context.
- Read [CONTRIBUTING.md](CONTRIBUTING.md) for development workflow, checks, and CI expectations.
- Use [docs/](docs/) for architecture, variant notes, and hardware documentation.

## Where to Find Things

- Repository layout and contribution flow: [CONTRIBUTING.md](CONTRIBUTING.md)
- Firmware code and components: [car/](car/)
- Controller code and tests: [controller/](controller/)
- Documentation and variant material: [docs/](docs/)
- Repo-level automation and helper scripts: [scripts/](scripts/)

## Working Rules for Agents

- Treat [README.md](README.md), [CONTRIBUTING.md](CONTRIBUTING.md), and [docs/](docs/) as authoritative.
- Prefer location-based discovery over hard-coded assumptions when looking for commands or procedures.
- Keep changes focused and update relevant docs when behavior or workflow changes.
- Hardware-affecting actions are manual-only unless explicitly requested by the user.

## Validation by Area

- Run minimal validation relevant to the touched area.
- For controller changes, use scripts under [controller/scripts/](controller/scripts/).
- For car firmware changes, use scripts and build flow under [car/scripts/](car/scripts/) and [CONTRIBUTING.md](CONTRIBUTING.md).
- For repo-wide checks/hooks, use [scripts/](scripts/).

## Docs and Generated Artifacts

- Documentation sources live under [docs/](docs/).
- Diagram sources and generated outputs are in [docs/plantuml/](docs/plantuml/).
- Use repository docs tooling from [scripts/](scripts/) to regenerate artifacts when needed.
- Prefer editing source files and regenerating derived outputs; avoid manual edits to generated files unless explicitly requested.
