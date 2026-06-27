#!/usr/bin/env bash
set -e

COMPONENT_DIR="${1?Usage: run_coverage_report.sh <component_dir>}"

source "$IDF_PATH/export.sh"

pushd "$COMPONENT_DIR" > /dev/null
lcov \
    --gcov-tool xtensa-esp-elf-gcov \
    --capture \
    --directory build \
    --output-file coverage.info \
    --ignore-errors mismatch \
    --quiet
genhtml coverage.info \
    --output-directory coverage \
    --quiet
popd > /dev/null
