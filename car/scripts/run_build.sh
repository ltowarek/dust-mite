#!/usr/bin/env bash
set -e

if [[ "${1:-}" == "--profiling" ]]; then
    export SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.profiling"
    shift
fi

COMPONENT_DIR="${1?Usage: run_build.sh [--profiling] <component_dir>}"

source "$IDF_PATH/export.sh"

pushd "$COMPONENT_DIR" > /dev/null
idf.py build
popd > /dev/null
