#!/bin/bash

if [ -f "$PRE_COMMIT_SCRIPT" ]; then
    . "$PRE_COMMIT_SCRIPT"
fi
