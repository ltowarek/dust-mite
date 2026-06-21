#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
# .env (UID/GID from scripts/dump_env.sh) is the single source of truth for the
# `user:` directive in the compose files, so the containers run as the host user
# and bind-mounted build/ and caches stay writable.
docker compose --env-file .env -f docker-compose.yml -f docker-compose.headless.yml up --build --remove-orphans -d
