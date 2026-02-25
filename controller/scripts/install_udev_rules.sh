#!/bin/bash

set -e

echo '
# USB
KERNEL=="hidraw*", SUBSYSTEM=="hidraw", ATTRS{idVendor}=="054c", ATTRS{idProduct}=="0ce6", MODE="0666", SYMLINK+="dual_sense"
# Bluetooth
KERNEL=="hidraw*", SUBSYSTEM=="hidraw", KERNELS=="0005:054C:0CE6.*", MODE="0666", SYMLINK+="dual_sense"
' > /etc/udev/rules.d/70-dualsense.rules

udevadm control --reload-rules
udevadm trigger
