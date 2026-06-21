#!/bin/bash

# Only reformats lines changed in the working tree/index, unlike
# run_clang_format.sh which checks the whole car/ tree.
git-clang-format --style=file -- ":/car"
