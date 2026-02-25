#!/bin/bash

if test -e "$CONTROLLER_DEVICE"; then
	echo "DualSense connected"
else
	echo "DualSense not connected"
fi
