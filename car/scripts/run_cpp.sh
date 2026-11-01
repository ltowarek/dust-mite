#!/usr/bin/env bash

set -e

# shellcheck source=/dev/null # ESP-IDF's export script is installed in the devcontainer image
source "$IDF_PATH/export.sh"
python "$IDF_PATH/tools/idf_monitor.py" -p /dev/ttyACM0
