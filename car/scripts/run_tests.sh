#!/usr/bin/env bash
set -e
source "$IDF_PATH/export.sh"

PORT="${PORT:-/dev/ttyACM0}"
CAR_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

TEST_PROJECTS=(
    "components/tracing/test"
    "components/camera/test"
    "components/motor/test"
    "components/telemetry/test"
    "components/web_server/test"
)

FAILED=0

for project in "${TEST_PROJECTS[@]}"; do
    echo "=== Building $project ==="
    (cd "$CAR_ROOT/$project" && idf.py build)

    echo "=== Testing $project ==="
    (cd "$CAR_ROOT/$project" && \
        pytest pytest_*.py --port "$PORT" -v) || FAILED=1
done

if [ "$FAILED" -ne 0 ]; then
    echo "=== Some tests failed ==="
    exit 1
fi

echo "=== All tests passed ==="
