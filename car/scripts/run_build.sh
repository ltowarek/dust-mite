#!/usr/bin/env bash
set -e

COMPONENT_DIR="${1?Usage: run_build.sh <component_dir>}"

source "$IDF_PATH/export.sh"

pushd "$COMPONENT_DIR" > /dev/null
idf.py build
popd > /dev/null
