#!/bin/bash

set -e

DEVICE="$($(dirname "$0")/find_dualsense.sh)"

hidapitester --list
hidapitester --open-path "$DEVICE" --read-input
