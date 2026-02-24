# DualSense setup for dust-mite

This guide explains how to:

1. Put a DualSense controller into pairing mode.
2. Find which `/dev/hidraw*` device Linux assigned to it.
3. Configure that device path in both [.env](../../.env) and [.devcontainer/python/devcontainer.json](../../.devcontainer/python/devcontainer.json).

## 1) Enter pairing mode

1. Turn the controller off.
2. Press and hold **Create** + **PS** buttons together for about 5 seconds.
3. Release when the light bar starts blinking rapidly (blue): this means pairing mode is active.

Pair the controller with the Linux PC.

If the controller does not connect because it was already connected previously, forget/remove the device in Linux Bluetooth settings and pair it again.

## 2) Find the DualSense hidraw device

After connecting the controller, list hidraw devices and inspect their metadata:

```bash
./controller/scripts/verify_hidapi.sh
```

In the script output, look for the `DualSense Wireless Controller` section and use its `path` field (for example, `/dev/hidraw8`) as your controller device.

## 3) Configure the device path in all required places

Use the same hidraw path everywhere.

### [.env](../../.env)

Set:

```env
CONTROLLER_DEVICE=/dev/hidraw8
```

### [.devcontainer/python/devcontainer.json](../../.devcontainer/python/devcontainer.json)

In `runArgs`, make sure the `"--device"` value matches the same path:

```jsonc
"runArgs": [
	"--device",
	"/dev/hidraw8",
	"--env-file",
	".env"
]
```

## 4) Restart container/session

After changing device mapping values:

1. Rebuild/reopen the devcontainer.
2. Reconnect the controller if needed.
3. Start the controller process again.

If the path is wrong or mismatched between [.env](../../.env) and [.devcontainer/python/devcontainer.json](../../.devcontainer/python/devcontainer.json), the controller may be visible on the host but unavailable inside the container.
