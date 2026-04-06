#!/bin/bash

DEVICE="$($(dirname "$0")/find_dualsense.sh)"

if [ -n "$DEVICE" ]; then
	echo "DualSense connected"
else
	echo "DualSense not connected"
fi
