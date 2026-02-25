# DualSense setup for dust-mite

This guide specifies the procedure to:

1. Configure a stable DualSense device mapping on Linux.
2. Put a DualSense controller into pairing mode and verify host-side visibility.
3. Configure the selected controller device path in both [.env](../../.env) and [.devcontainer/python/devcontainer.json](../../.devcontainer/python/devcontainer.json).
4. Start the Python devcontainer and verify controller visibility.

## 1) Find the DualSense hidraw mapping

Create a stable alias (`/dev/dual_sense`) so reconnects/reboots do not change the path.

Install the udev rule on the host:

```bash
sudo ./controller/scripts/install_udev_rules.sh
```

This creates `/etc/udev/rules.d/70-dualsense.rules`, reloads rules, and maps the controller to `/dev/dual_sense`.

If required, an explicit `/dev/hidrawN` path can still be provided manually, but it may change between reconnects/reboots.

## 2) Enter pairing mode

1. Turn the controller off.
2. Press and hold **Create** + **PS** buttons together for about 5 seconds.
3. Release when the light bar starts blinking rapidly (blue): this means pairing mode is active.

Pair the controller with the Linux PC.

Connection verification:

```bash
CONTROLLER_DEVICE=/dev/dual_sense ./controller/scripts/verify_dualsense_connection.sh
```

If the controller does not connect because of an existing pairing record, remove the device in Linux Bluetooth settings and repeat the pairing procedure.

## 3) Configure the device path in all required places

Use a consistent device path in all configuration locations.

### [.env](../../.env)

Set:

```env
CONTROLLER_DEVICE=/dev/dual_sense
```

### [.devcontainer/python/devcontainer.json](../../.devcontainer/python/devcontainer.json)

In `runArgs`, ensure the `"--device"` value matches the same path:

```jsonc
"runArgs": [
	"--device",
	"/dev/dual_sense",
	"--env-file",
	".env"
]
```

## 4) Start the Python devcontainer and verify controller visibility

1. Rebuild or reopen the `Python` devcontainer.
2. In the devcontainer terminal, verify HID visibility:

	```bash
	./controller/scripts/verify_hidapi.sh
	```

	Verify that `DualSense Wireless Controller` is listed.
3. Start the controller process:

	```bash
	python ./controller/src/controller/controller.py
	```

If the controller is not visible in step 2, verify `CONTROLLER_DEVICE` in [.env](../../.env), validate the `--device` mapping in [.devcontainer/python/devcontainer.json](../../.devcontainer/python/devcontainer.json), and reconnect the controller on the host.
