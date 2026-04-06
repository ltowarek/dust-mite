#!/bin/bash

set -e

for uevent in /sys/class/hidraw/*/device/uevent; do
    grep -qi "HID_ID=.*:0000054C:00000CE6" "$uevent" 2>/dev/null || continue
    hidraw_dir="${uevent%/device/uevent}"
    echo "/dev/${hidraw_dir##*/}"
    exit 0
done

echo "DualSense not found" >&2
exit 1
