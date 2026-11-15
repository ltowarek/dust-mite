#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
trap ./scripts/stop_headless.sh EXIT

docker compose --env-file .env -p dust-mite-dut -f .devcontainer/cpp/docker-compose.yml -f docker-compose.car.yml \
    run --rm --build -w /workspaces/dust-mite/car cpp ./scripts/run_tests.sh
# Runs before the headless stack, which would otherwise hold the car's endpoints.
docker compose --env-file .env -p dust-mite-dut -f .devcontainer/python/docker-compose.yml \
    run --rm --build -w /workspaces/dust-mite/controller python ./scripts/run_tests.sh -- tests/integration --dut
./scripts/start_headless.sh
# Runs before the observability suite, which needs recent traffic from the Web app.
docker compose --env-file .env -f docker-compose.yml -f docker-compose.headless.yml \
    exec test-runner ./scripts/run_tests.sh tests/e2e/full_stack
docker compose --env-file .env -p dust-mite-dut -f .devcontainer/observability/docker-compose.yml \
    run --rm --build -w /workspaces/dust-mite/observability observability ./scripts/run_tests.sh -- tests/e2e --dut
