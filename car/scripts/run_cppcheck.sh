#!/bin/bash
set -e

SCRIPTPATH=$(dirname "$0")
CAR_ROOT="$(cd "$SCRIPTPATH/.." && pwd)"

SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.all" idf.py -C "$CAR_ROOT" build > /dev/null

cppcheck --project="$CAR_ROOT/build/compile_commands.json" \
    --enable=warning,performance,portability,style \
    --suppressions-list="$CAR_ROOT/.cppcheck-suppressions" \
    --inline-suppr \
    --error-exitcode=1 \
    --quiet \
    "$@" \
    --file-filter="$CAR_ROOT/main/*" \
    --file-filter="$CAR_ROOT/components/camera/*" \
    --file-filter="$CAR_ROOT/components/motor/*" \
    --file-filter="$CAR_ROOT/components/telemetry/*" \
    --file-filter="$CAR_ROOT/components/tracing/*" \
    --file-filter="$CAR_ROOT/components/web_server/*" \
    --file-filter="$CAR_ROOT/components/wifi/*"
