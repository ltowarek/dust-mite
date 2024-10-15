#!/bin/bash

set -e

apt install libhidapi-dev

echo '
# USB
KERNEL=="hidraw*", SUBSYSTEM=="hidraw", ATTRS{idVendor}=="054c", ATTRS{idProduct}=="0ce6", MODE="0666"
# Bluetooth
KERNEL=="hidraw*", SUBSYSTEM=="hidraw", KERNELS=="0005:054C:0CE6.*", MODE="0666"
' > /etc/udev/rules.d/70-dualsense.rules

udevadm control --reload-rules
udevadm trigger
