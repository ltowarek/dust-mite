#!/bin/bash

if [ -f "$PRE_COMMIT_SCRIPT" ]; then
    # shellcheck source=/dev/null # each devcontainer sets the delegated script at runtime
    . "$PRE_COMMIT_SCRIPT"
fi
