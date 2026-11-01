#!/usr/bin/env bash
set -e

COMPONENT_DIR="${1?Usage: run_qemu_tests.sh <component_dir> <pytest_pattern> [pytest_args...]}"
PYTEST_PATTERN="${2?Usage: run_qemu_tests.sh <component_dir> <pytest_pattern> [pytest_args...]}"

# shellcheck source=/dev/null # ESP-IDF's export script is installed in the devcontainer image
source "$IDF_PATH/export.sh"

pushd "$COMPONENT_DIR" >/dev/null
python -m pytest "$PYTEST_PATTERN" --embedded-services idf,qemu --junitxml=results.xml "${@:3}" -v
popd >/dev/null
