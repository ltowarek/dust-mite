#!/bin/bash
set -e

SCRIPTPATH=$(dirname "$0")
CAR_ROOT="$(cd "$SCRIPTPATH/.." && pwd)"

mapfile -t FILES < <(find "$CAR_ROOT/main" "$CAR_ROOT/components" "$CAR_ROOT/test_apps" \
    -path '*/managed_components/*' -prune -o \
    -path '*/build/*' -prune -o \
    -path '*/esp-opentelemetry-cpp/*' -prune -o \
    -path '*/DFRobot_AXP313A/*' -prune -o \
    -type f \( -name '*.cpp' -o -name '*.hpp' -o -name '*.h' -o -name '*.c' \) -print | sort)

clang-format --style=file "$@" "${FILES[@]}"
