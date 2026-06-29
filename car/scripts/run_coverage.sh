#!/usr/bin/env bash
set -e

COMPONENT_DIR="${1?Usage: run_coverage.sh <component_test_app_dir> <pytest_pattern>}"
PYTEST_PATTERN="${2?Usage: run_coverage.sh <component_test_app_dir> <pytest_pattern>}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.qemu;sdkconfig.defaults.coverage" \
    "$SCRIPT_DIR/run_build.sh" "$COMPONENT_DIR"

if [[ -z "${QEMU_PROG_PATH}" ]]; then
    echo "QEMU_PROG_PATH must be set to patched qemu-system-xtensa binary" >&2
    exit 1
fi
QEMU_SHARE_DIR="$(dirname "$(dirname "$QEMU_PROG_PATH")")/share/qemu"
[[ -d "$QEMU_SHARE_DIR" ]] || { echo "QEMU share dir not found: $QEMU_SHARE_DIR" >&2; exit 1; }

test_exit=0
COVERAGE_BUILD=1 "$SCRIPT_DIR/run_qemu_tests.sh" "$COMPONENT_DIR" "$PYTEST_PATTERN" \
    "--qemu-prog-path=$QEMU_PROG_PATH" \
    "--qemu-extra-args=-machine esp32s3,app-trace=file_io -L $QEMU_SHARE_DIR" || test_exit=$?
"$SCRIPT_DIR/run_coverage_report.sh" "$COMPONENT_DIR"
exit $test_exit
