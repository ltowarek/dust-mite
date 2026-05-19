#!/usr/bin/env bash

set -e

source "$IDF_PATH/export.sh"
git config --global --add safe.directory "*"
cd /workspaces/dust-mite/car
idf.py -B /home/vscode/build build
idf.py -B /home/vscode/build flash
idf.py -B /home/vscode/build monitor
