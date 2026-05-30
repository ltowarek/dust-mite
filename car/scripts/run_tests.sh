#!/usr/bin/env bash
set -e
source "$IDF_PATH/export.sh"

PORT="${PORT:-/dev/ttyACM0}"
CAR_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CLEAN=0

for arg in "$@"; do
    case "$arg" in
        --clean) CLEAN=1 ;;
    esac
done

COMPONENT_TEST_PROJECTS=(
    "components/tracing/test_apps"
    "components/camera/test_apps"
    "components/motor/test_apps"
    "components/telemetry/test_apps"
    "components/web_server/test_apps"
)

FAILED=0

build() {
    local dir="$1"
    pushd "$dir" > /dev/null
    if [ "$CLEAN" -eq 1 ]; then
        idf.py fullclean
    fi
    idf.py build
    popd > /dev/null
}

for project in "${COMPONENT_TEST_PROJECTS[@]}"; do
    echo "=== Building $project ==="
    build "$CAR_ROOT/$project"

    echo "=== Testing $project ==="
    pushd "$CAR_ROOT/$project" > /dev/null
    pytest pytest_*.py --ignore-glob '*_qemu.py' \
        --embedded-services idf,esp --port "$PORT" -v || FAILED=1
    popd > /dev/null
done

echo "=== Building integration tests ==="
build "$CAR_ROOT/test_apps/integration"

echo "=== Running integration tests ==="
pushd "$CAR_ROOT/test_apps/integration" > /dev/null
pytest pytest_integration.py --port "$PORT" --embedded-services idf,esp -v || FAILED=1
popd > /dev/null

echo "=== Building production firmware for E2E ==="
build "$CAR_ROOT"

echo "=== Running E2E tests ==="
pushd "$CAR_ROOT/test_apps/e2e" > /dev/null
pytest pytest_e2e.py --port "$PORT" --embedded-services idf,esp -v || FAILED=1
popd > /dev/null

if [ "$FAILED" -ne 0 ]; then
    echo "=== Some tests failed ==="
    exit 1
fi

echo "=== All tests passed ==="
