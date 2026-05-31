# AGENTS

This file is a lightweight navigation guide for coding agents.

- Source-of-truth guidance lives in existing project docs.
- This file intentionally avoids duplicating procedural details.

## Table of Contents

1. [Start Here](#start-here)
2. [Where to Find Things](#where-to-find-things)
3. [Running the Full Stack (Headless)](#running-the-full-stack-headless)
4. [Working Rules for Agents](#working-rules-for-agents)
5. [Validation by Area](#validation-by-area)
6. [Docs and Generated Artifacts](#docs-and-generated-artifacts)

## Start Here

- Read [README.md](README.md) for project orientation and high-level context.
- Read [CONTRIBUTING.md](CONTRIBUTING.md) for development workflow, checks, and CI expectations.
- Use [docs/](docs/) for architecture, variant notes, and hardware documentation.

## Where to Find Things

- Repository layout and contribution flow: [CONTRIBUTING.md](CONTRIBUTING.md)
- Firmware code and components: [car/](car/)
- Controller code, tests, and Raspberry Pi camera service: [controller/](controller/)
- Web frontend code: [web/](web/)
- Documentation and variant material: [docs/](docs/)
- Repo-level automation and helper scripts: [scripts/](scripts/)

## Running the Full Stack (Headless)

Run `./scripts/start_headless.sh` to build and start all services in the background.
Run `./scripts/stop_headless.sh` to stop and remove all containers.

Docker Compose services: `cpp`, `python`, `js`, `otel-collector`, `tempo`, `grafana`. Use standard docker compose commands to manage them:

- Logs: `docker compose -f docker-compose.yml -f docker-compose.headless.yml logs [-f] <service>`
- Restart: `docker compose -f docker-compose.yml -f docker-compose.headless.yml restart <service>`

Grafana is available at `http://localhost:3000` for trace exploration.

## Working Rules for Agents

- Treat [README.md](README.md), [CONTRIBUTING.md](CONTRIBUTING.md), and [docs/](docs/) as authoritative.
- Run all commands inside the appropriate devcontainer, not on the host. See [CONTRIBUTING.md](CONTRIBUTING.md) for available environments.
- For the C++ devcontainer: the image is built from [.devcontainer/cpp/Dockerfile](.devcontainer/cpp/Dockerfile). Find the running container with `docker ps` (service name `cpp`) and run commands via `docker exec <name> bash -c "source /opt/esp/idf/export.sh && <command>"`. ESP-IDF lives at `/opt/esp/idf/`; QEMU (`qemu-system-xtensa`) is installed in the container. The linux IDF target is not available.
- Prefer location-based discovery over hard-coded assumptions when looking for commands or procedures.
- Keep changes focused and update relevant docs when behavior or workflow changes.
- For documentation updates, follow the formal technical writing rules in [CONTRIBUTING.md](CONTRIBUTING.md).
- Hardware-affecting actions are manual-only unless explicitly requested by the user.

## Validation by Area

- Run minimal validation relevant to the touched area.
- For controller changes, use scripts under [controller/scripts/](controller/scripts/).
- For web frontend changes, use scripts under [web/scripts/](web/scripts/).
- For car firmware changes, use scripts and build flow under [car/scripts/](car/scripts/) and [CONTRIBUTING.md](CONTRIBUTING.md).
- For repo-wide checks/hooks, use [scripts/](scripts/).

## Docs and Generated Artifacts

- Documentation sources live under [docs/](docs/).
- Diagrams are written in Mermaid and embedded directly in the relevant documentation files; no separate generation step is needed.
- Use repository docs tooling from [scripts/](scripts/) to regenerate image artifacts (logos, optimized images) when needed.
- Prefer editing source files and regenerating derived outputs; avoid manual edits to generated files unless explicitly requested.

## Firmware Flashing and Serial Monitoring

Always use `idf.py flash` and `idf.py monitor` (via ESP-IDF) for flashing and serial
capture. Do NOT use pyserial, esptool directly, or any custom Python serial code.

`idf.py monitor` requires both stdin and stdout to be a TTY. In non-interactive shells
`ESP_IDF_MONITOR_TEST=1` is not sufficient — wrap the command with `script -q -c "..." /tmp/out.txt`
to provide a pseudo-TTY, then read the output file.

Example (inside the C++ devcontainer):
```bash
script -q -c "idf.py -p /dev/ttyACM0 monitor" /tmp/monitor.txt
# wait for desired output, then Ctrl-C
cat /tmp/monitor.txt
```

When rebuilding after a `sdkconfig.defaults` or Kconfig change, delete only
`sdkconfig` (not the whole `build/` directory) — IDF detects the stale config
and reconfigures automatically, avoiding a full rebuild.
