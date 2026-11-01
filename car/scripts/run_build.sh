#!/usr/bin/env bash
set -e

if [[ "${1:-}" == "--debug" ]]; then
    export SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.debug"
    shift
fi

COMPONENT_DIR="${1?Usage: run_build.sh [--debug] <component_dir>}"

# shellcheck source=/dev/null # ESP-IDF's export script is installed in the devcontainer image
source "$IDF_PATH/export.sh"

pushd "$COMPONENT_DIR" >/dev/null
idf.py build
popd >/dev/null
