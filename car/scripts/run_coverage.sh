#!/usr/bin/env bash
set -e

COMPONENT_DIR="${1?Usage: run_coverage.sh <component_test_app_dir> <pytest_pattern>}"
PYTEST_PATTERN="${2?Usage: run_coverage.sh <component_test_app_dir> <pytest_pattern>}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.qemu;sdkconfig.defaults.coverage" \
    "$SCRIPT_DIR/run_build.sh" "$COMPONENT_DIR"
"$SCRIPT_DIR/run_qemu_tests.sh" "$COMPONENT_DIR" "$PYTEST_PATTERN" --qemu-extra-args="-semihosting"
"$SCRIPT_DIR/run_coverage_report.sh" "$COMPONENT_DIR"
