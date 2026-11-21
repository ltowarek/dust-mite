# Python projects declare their dependencies in pyproject.toml and lock them with uv

The Python projects declared their dependencies in pip-compile-multi `.in` files, so the packages carried no dependency metadata, and each `.txt` lock was resolved only for the platform and Python that compiled it. `controller/requirements/rpi.txt` was compiled on x86 with Python 3.12 and installed on a Raspberry Pi with Python 3.11 ([#374](https://github.com/ltowarek/dust-mite/issues/374)).

Every Python project is therefore a uv project: `controller/`, `observability/`, `tools/afk/`, `car/` (the QEMU and DUT test requirements) and `.devcontainer/infrastructure/` (yamllint and zizmor). Each declares its runtime dependencies under `[project] dependencies` and its development tools in a `dev` dependency group (PEP 735), pins its interpreter in a `.python-version` file, and commits one universal `uv.lock` that covers every group, platform and allowed Python version. A project without a package, such as `observability/` or `car/`, sets `[tool.uv] package = false`. The Raspberry Pi's dependencies are the controller's `rpi` group, because the Pi is another host for the controller, not a project of its own. The Pi moves to Raspberry Pi OS Trixie, whose system Python 3.13 meets the controller's `requires-python`, so the Pi installs from the controller's lock with uv like every other host.

uv replaces pip-compile-multi, tox and the hand-written venvs. The scripts stay the entry points and run uv inside: `uv lock --check` replaces `pip-compile-multi verify`, and `uv run pytest` replaces tox. Images get uv from its GitHub release archive pinned by `ARG UV_VERSION`, as the infrastructure image gets its other binary tools, and use the base image's Python with `UV_PYTHON_DOWNLOADS=never`. A devcontainer keeps its environment in the image, outside the bind-mounted workspace, through `UV_PROJECT_ENVIRONMENT`.

## Considered Options

- **Keep pip-compile-multi and compile `rpi.txt` on the Pi.** Rejected: the lock still covers one platform at a time, and the packages still carry no metadata.
- **pip-tools with `pyproject.toml` input.** Rejected: it fixes the metadata but still resolves for one platform and one Python per compiled file.
- **One uv workspace for all projects.** Rejected: a workspace has one lock and one `requires-python`, which clashes with `afk`'s Python 3.11, the controller's 3.12 and observability's pinned `ruff` and `mypy`.
- **A separate uv project for the Pi, with its own `requires-python = ">=3.11"`.** Rejected: the [Iron](../variants/iron.md) variant runs the controller itself on the Pi, and [#188](https://github.com/ltowarek/dust-mite/issues/188) has the Pi's camera service reuse controller code. The Pi's Python is the controller's concern.
- **Keep the Pi on Bookworm and install an exported requirements file with pip.** Rejected: Bookworm's Python 3.11 is below the controller's `requires-python`, so the lock would not cover the Pi, and the Pi would keep an install path of its own.
- **A uv-managed Python 3.12 on the Pi.** Rejected: the apt `python3-libcamera` that `picamera2` needs is built only for the system Python, so the Pi's venv must use the system interpreter.
- **Copying uv from its Docker image, as uv's Docker guide recommends.** Deferred: no Dockerfile copies a tool from another image yet, and [#386](https://github.com/ltowarek/dust-mite/issues/386) decides that for every pinned binary tool at once.

## Consequences

- Ansible installs uv on the Pi from its pinned `armv7` release archive, creates the Pi's venv on the system Python with `--system-site-packages`, so the apt `python3-picamera2` stays importable, and syncs only the controller's `rpi` group into it. The Pi passes its interpreter explicitly, because the controller's `.python-version` names 3.12.
- The controller now runs on Python 3.12 on the development host and 3.13 on the Pi; testing it on both is [#20](https://github.com/ltowarek/dust-mite/issues/20).
- The infrastructure image holds two uv projects in two venvs, because `uv sync` and `uv run` remove every package their project does not lock: its tools in `/opt/venv`, on `PATH`, and `afk`'s environment in the venv that `UV_PROJECT_ENVIRONMENT` names.
- The car's test requirements install into ESP-IDF's own venv, through `uv pip install --python` with the file `uv export` writes.
- The production controller image installs with `uv sync --no-dev`, so its runtime carries no development tools.
- The checks that [ADR 0008](0008-complex-automation-logic-in-tested-python.md) lists for Python projects become `pytest` through `uv run` and `uv lock --check`.
- Dependabot updates the locks through its `uv` ecosystem ([#373](https://github.com/ltowarek/dust-mite/issues/373)), but not `UV_VERSION` ([#386](https://github.com/ltowarek/dust-mite/issues/386)).
