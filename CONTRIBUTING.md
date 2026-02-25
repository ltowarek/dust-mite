# Contributing to dust-mite

Thanks for contributing.
This repository is an experimentation playground, so contributions that improve learning value, clarity, and iteration speed are especially welcome.

## Ground rules

- Keep changes focused and easy to review.
- Prefer small pull requests over large rewrites.
- Preserve existing style and tooling unless a change explicitly updates them.
- Open or reference a GitHub Issue for bugs, tasks, and larger proposals.

## Prerequisites

- Docker
- VS Code with Dev Containers support

## Initial setup

From repository root:

```bash
./scripts/install_git_hooks.sh
```

This installs a Git pre-commit hook that can run project checks.

The hook delegates to container-specific pre-commit scripts via `PRE_COMMIT_SCRIPT` configured in each devcontainer.

## Development environment

This project is designed to be developed in VS Code Dev Containers.
Use devcontainers as the default workflow for all contributions.

Available environments:

- [.devcontainer/python/](.devcontainer/python/) for [controller/](controller/) work
- [.devcontainer/cpp/](.devcontainer/cpp/) for [car/](car/) firmware work
- [.devcontainer/docs/](.devcontainer/docs/) for [docs/](docs/) updates (diagrams and image processing)

### Open the correct workspace in container

1. Open the repository in VS Code.
2. From repository root, generate [.env](.env):

   ```bash
   ./scripts/dump_env.sh
   ```

3. Edit [.env](.env) and provide correct values for your setup (for example Wi-Fi SSID/password and other required variables).
4. Open the target locally first in VS Code:
   - For [python.code-workspace](python.code-workspace) or [cpp.code-workspace](cpp.code-workspace):
     1. Run `File: Open Workspace from File...`.
     2. Choose [python.code-workspace](python.code-workspace) for [controller/](controller/) work, or [cpp.code-workspace](cpp.code-workspace) for [car/](car/) work.
   - For docs work: no additional action is required; continue with the repository root opened in step 1.
5. If you need hardware passthrough (for example controller or ESP32 device access), manually uncomment the `--device` entries in:
   - [.devcontainer/python/devcontainer.json](.devcontainer/python/devcontainer.json)
   - [.devcontainer/cpp/devcontainer.json](.devcontainer/cpp/devcontainer.json)
6. Run `Dev Containers: Reopen in Container` and choose the matching devcontainer (`Python`, `C++`, or `Docs`).

The container image includes project dependencies and VS Code extensions required for that stack.

#### Why VS Code workspace files are used

- A plain single-root workspace is not a good fit for this repository layout when using the ESP-IDF extension. The extension expects the workspace root to match an ESP-IDF project structure (see the [ESP-IDF example project layout](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/build-system.html#example-project)).
- Pointing `workspaceFolder` directly to [car/](car/) makes ESP-IDF tooling work reliably, but then editing files at repository root (for example docs or devcontainer config) becomes terminal-only and cumbersome.
- Using [cpp.code-workspace](cpp.code-workspace) keeps [car/](car/) as the active project while still exposing the repository root in the same VS Code session.
- Keep workspace files (for example [cpp.code-workspace](cpp.code-workspace) and [python.code-workspace](python.code-workspace)) at repository root. If a `.code-workspace` file is stored in a subfolder, Dev Containers can't resolve that subfolder's parent as the shared directory.

## Variants

Variants use code names based on chemical elements (for example `Copper`, `Iron`).

Each new variant must include:

- A dedicated logo in [docs/images/logos/](docs/images/logos/).
- Variant photos in [docs/images/](docs/images/).
- Variant documentation in [docs/variants/](docs/variants/).
- An entry in [docs/variants.md](docs/variants.md).

## Repository map

- [car/](car/) - ESP-IDF firmware for the RC car platform.
- [controller/](controller/) - Python controller, stream/telemetry integration.
- [docs/](docs/) - project documentation.
- [scripts/](scripts/) - repository-level helper scripts.

## Controller development ([controller/](controller/))

In the Python devcontainer, the workspace opens at `/workspace/controller`.

### Run quality checks

```bash
./scripts/run_checks.sh
```

If checks fail, apply automatic fixes:

```bash
./scripts/fix_checks.sh
```

### Run tests

```bash
./scripts/run_tests.sh
```

### Controller test types

- Unit tests: validate individual controller modules and functions in isolation using focused test doubles where needed; implemented in [controller/tests/unit/](controller/tests/unit/).
- Integration tests: validate interactions across controller boundaries (for example websocket communication and packet flow) using multi-component test scenarios; implemented in [controller/tests/integration/](controller/tests/integration/).
- E2E tests: validate full user-level control flows across the complete stack (controller input to observable car behavior and outputs) in realistic deployment conditions; not implemented yet.

Run specific suites:

```bash
./scripts/run_tests.sh tests/unit
./scripts/run_tests.sh tests/integration
```

### Dependency updates

```bash
./scripts/update_requirements.sh
./scripts/upgrade_requirements.sh
./scripts/upgrade_package.sh <package_name>
./scripts/run_requirements_checks.sh
```

### Dependency management

This project uses [pip-compile-multi](https://pypi.org/project/pip-compile-multi/) for hard-pinning dependencies versions.
Please see its documentation for usage instructions.
In short, `requirements/base.in` contains the list of direct requirements with occasional version constraints (like `Django<2`)
and `requirements/base.txt` is automatically generated from it by adding recursive tree of dependencies with fixed versions.
The same goes for `test` and `dev`.

To upgrade dependency versions, run `pip-compile-multi`.

To add a new dependency without upgrade, add it to `requirements/base.in` and run `pip-compile-multi --no-upgrade`.

For installation always use `.txt` files. For example, command `pip install -Ue . -r requirements/dev.txt` will install
this project in development mode, testing requirements and development tools.
Another useful command is `pip-sync requirements/dev.txt`, it uninstalls packages from your virtualenv that aren't listed in the file.

## Car firmware development ([car/](car/))

[car/](car/) is an ESP-IDF project.
In the C++ devcontainer, the ESP-IDF environment is already configured.
The C++ devcontainer opens at `/workspace/car`.

Typical loop:

```bash
idf.py build
idf.py flash
idf.py monitor
```

### Car test types

- Component tests: Unity-based tests focused on a single firmware component API/behavior, implemented in each component `test/` directory and run through the ESP-IDF test app, for example:
  - [car/components/camera/test/](car/components/camera/test/)
  - [car/components/motor/test/](car/components/motor/test/)
  - [car/components/telemetry/test/](car/components/telemetry/test/)
  - [car/components/web_server/test/](car/components/web_server/test/)
- Test runner app: [car/test/](car/test/) is a dedicated ESP-IDF test project that collects and runs selected component tests.
- Integration tests: validate interactions between multiple car components (for example command handling, telemetry, and web server behavior together) on target-like runtime conditions; not implemented yet.
- E2E tests: validate complete end-to-end driving flows (input/control path to observable car behavior and outputs) in realistic deployment conditions; not implemented yet.

Build test firmware:

```bash
cd test
idf.py build
```

## Documentation

Use the `Docs` devcontainer for documentation updates that require PlantUML/Graphviz/ImageMagick tooling.

Open repository root in the `Docs` devcontainer and run documentation scripts from repository root.

### Diagrams

Documentation diagrams are generated from PlantUML sources.

Generate all diagrams from repository root:

```bash
./scripts/generate_plantuml_diagrams.sh
```

The script reads `.puml` files from [docs/plantuml/](docs/plantuml/) and regenerates `.svg` outputs in the same directory.

### Images

Documentation images should be optimized and branded consistently before they are committed.

When adding new documentation images:

1. Put the image under [docs/images/](docs/images/).
2. Optimize it:

   ```bash
   ./scripts/optimize_image.sh <path_to_image.jpg>
   ```

3. Apply logo overlay (available under [docs/images/logos/](docs/images/logos/)):

   ```bash
   ./scripts/apply_logo.sh <path_to_logo.svg> <path_to_image.jpg>
   ```

## CI/CD

GitHub Actions workflows are defined in [.github/workflows/](.github/workflows/).

- [python-controller.yml](.github/workflows/python-controller.yml)
  - Triggers on pull requests and pushes to `main`
  - Builds and publishes the Python devcontainer image from [.devcontainer/python/Dockerfile](.devcontainer/python/Dockerfile)
  - Runs controller checks in container: lint, format check, type checks, requirements checks, and tests
- [cpp-car.yml](.github/workflows/cpp-car.yml)
  - Triggers on pull requests and pushes to `main`
  - Builds and publishes the C++ devcontainer image from [.devcontainer/cpp/Dockerfile](.devcontainer/cpp/Dockerfile)
  - Runs firmware build for [car/](car/) and test build for [car/test/](car/test/)

Before opening a pull request, run the relevant local checks in the matching devcontainer to reduce CI failures.

## Pull request checklist

- Reference the related GitHub Issue (or explain why none is needed).
- Keep PR description clear: motivation, scope, and validation steps.
- Run relevant checks/tests for the component you changed.
- Update docs ([README.md](README.md), [docs/](docs/)) when behavior or workflows change.

## AGENTS.md

[AGENTS.md](AGENTS.md) is a table-of-contents style index for coding agents.
It links to authoritative guidance in [README.md](README.md), [CONTRIBUTING.md](CONTRIBUTING.md), and [docs/](docs/) instead of duplicating procedures.

When documentation structure or workflows change, keep [AGENTS.md](AGENTS.md) in sync in the same pull request so agent navigation remains accurate.
