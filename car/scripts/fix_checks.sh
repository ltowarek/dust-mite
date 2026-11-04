#!/bin/bash
# shellcheck source=/dev/null # ESP-IDF's export script is installed in the devcontainer image
source "$IDF_PATH/export.sh"

# Only reformats lines changed in the working tree/index, unlike
# run_clang_format.sh which checks the whole car/ tree.
git-clang-format --style=file -- ":/car"
