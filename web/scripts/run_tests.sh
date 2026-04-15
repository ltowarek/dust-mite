#!/bin/bash

set -e

if [ "$1" = "tests/e2e" ]; then
    npx playwright test "${@:2}"
elif [ $# -eq 0 ]; then
    npx vp test --run
    npx playwright test
else
    npx vp test --run "$@"
fi
