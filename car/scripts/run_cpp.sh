#!/usr/bin/env bash

set -e

source "$IDF_PATH/export.sh"
python "$IDF_PATH/tools/idf_monitor.py" -p /dev/ttyACM0
