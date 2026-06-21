#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
# Use the same --env-file so compose resolves the same `user:` (host UID/GID).
docker compose --env-file .env -f docker-compose.yml -f docker-compose.headless.yml down
