#!/usr/bin/env bash
set -e

COMPONENT_DIR="${1?Usage: run_qemu_tests.sh <component_dir> <pytest_pattern> [pytest_args...]}"
PYTEST_PATTERN="${2?Usage: run_qemu_tests.sh <component_dir> <pytest_pattern> [pytest_args...]}"

source "$IDF_PATH/export.sh"

pushd "$COMPONENT_DIR" > /dev/null
python -m pytest "$PYTEST_PATTERN" --embedded-services idf,qemu "${@:3}" -v
popd > /dev/null
