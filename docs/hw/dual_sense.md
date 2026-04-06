# DualSense setup for dust-mite

This guide specifies the procedure to:

1. Configure non-root hidraw access on Linux and find the DualSense hidraw path.
2. Put a DualSense controller into pairing mode and verify host-side visibility.
3. Configure the devcontainer device passthrough in [.devcontainer/python/docker-compose.yml](../../.devcontainer/python/docker-compose.yml).
4. Start the Python devcontainer and verify controller visibility.

## 1) Install udev rule and find the DualSense hidraw path

Install the udev rule on the host to grant non-root read/write access to the hidraw device:

```bash
sudo ./controller/scripts/install_udev_rules.sh
```

This creates `/etc/udev/rules.d/70-dualsense.rules` and reloads rules.

### Find the hidraw path

```bash
./controller/scripts/find_dualsense.sh
```

Example output: `/dev/hidraw4`

The `hidrawN` number may change if the controller is reconnected or the host is rebooted. Re-run the script and update the configuration if the number changes.

## 2) Enter pairing mode

1. Turn the controller off.
2. Press and hold **Create** + **PS** buttons together for about 5 seconds.
3. Release when the light bar starts blinking rapidly (blue): this means pairing mode is active.

Pair the controller with the Linux PC.

Connection verification:

```bash
./controller/scripts/verify_dualsense_connection.sh
```

If the controller does not connect because of an existing pairing record, remove the device in Linux Bluetooth settings and repeat the pairing procedure.

## 3) Configure the devcontainer device passthrough

Run [`find_dualsense.sh`](../../controller/scripts/find_dualsense.sh) to get the current hidraw path and update the following location.

### [.devcontainer/python/docker-compose.yml](../../.devcontainer/python/docker-compose.yml)

Uncomment the `devices` section and set the entry. Replace `hidrawN` with the path found in step 1:

```yaml
devices:
  - /dev/hidrawN:/dev/hidrawN
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
	controller
	```

If the controller is not visible in step 2, validate the `devices` entry in [.devcontainer/python/docker-compose.yml](../../.devcontainer/python/docker-compose.yml) and reconnect the controller on the host.
