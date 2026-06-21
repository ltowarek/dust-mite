#!/usr/bin/env bash
set -e
source "$IDF_PATH/export.sh"

CAR_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

export IDF_TOOLCHAIN=clang

pushd "$CAR_ROOT" > /dev/null

# Building with clang is still experimental in ESP-IDF (see CONTRIBUTING.md);
# known TLS-relocation link failures in vendored deps are expected here. We
# only need compile_commands.json, not a successful link.
idf.py build > /dev/null 2>&1 || true

if [ ! -f "$CAR_ROOT/build/compile_commands.json" ]; then
    echo "compile_commands.json missing - build failed before code generation"
    exit 1
fi

idf.py clang-check \
    --exclude-paths build \
    --exclude-paths managed_components \
    --exclude-paths components/esp-opentelemetry-cpp \
    --exclude-paths components/DFRobot_AXP313A \
    --run-clang-tidy-options "-config-file=$CAR_ROOT/.clang-tidy" \
    --exit-code "$@"

popd > /dev/null
