#!/bin/bash

set -e

if [ "$1" = "tests/e2e/full_stack" ]; then
    # Requires the headless stack to be running (./scripts/start_headless.sh).
    npx playwright test --project=full_stack
elif [ "$1" = "tests/e2e" ]; then
    npx playwright test --project=firefox "${@:2}"
elif [ $# -eq 0 ]; then
    npx vp test run --coverage
    npx playwright test --project=firefox
else
    npx vp test run --coverage "$@"
fi
