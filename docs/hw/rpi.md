# Raspberry Pi synchronization and provisioning

This document defines the high-level workflow for preparing Raspberry Pi OS (Bookworm Lite) to run the dust-mite camera runtime using Ansible automation from the controller workspace.

## Files

- Playbook: [controller/ansible/setup_rpi.yml](../../controller/ansible/setup_rpi.yml)
- Runner script: [controller/scripts/setup_rpi.sh](../../controller/scripts/setup_rpi.sh)

## Python version note

The Python devcontainer uses Python 3.12, while Raspberry Pi OS Bookworm typically provides system Python 3.11. The Raspberry Pi provisioning workflow intentionally uses the system Python toolchain to keep runtime setup compatible with `picamera2` packaging on Raspberry Pi OS.

## Provisioning workflow

### 1. Prepare a fresh Raspberry Pi OS image

Flash Raspberry Pi OS (Bookworm Lite) and complete [Raspberry Pi Imager](https://www.raspberrypi.com/documentation/computers/getting-started.html#raspberry-pi-imager) customization before first boot. Configure at minimum:

- user account (for example `pi`)
- SSH enabled
- network settings required for host reachability

### 2. Complete initial Raspberry Pi host setup

After first boot, update the operating system:

```bash
sudo apt update
sudo apt full-upgrade -y
sudo reboot
```

After reboot, verify that the camera is detected by the Bookworm `libcamera` stack:

```bash
libcamera-hello --list-cameras
```

### 3. Configure repository environment variables

This workflow assumes [scripts/dump_env.sh](../../scripts/dump_env.sh) has already been executed and a repository [.env](../../.env) file is available. Customize [.env](../../.env) with Raspberry Pi connection parameters so the provisioning script can resolve host and user values.

Ensure the following keys are set correctly:

```bash
RPI_ADDRESS=<raspberry_pi_hostname_or_ip>
RPI_USERNAME=<raspberry_pi_user>
```

From repository root, load `.env` values into the current shell before running provisioning:

```bash
source ./scripts/load_env.sh
```

### 4. Establish SSH key-based access from the development host

If an SSH key is not available on the development host, generate one:

```bash
ssh-keygen
```

Copy the local SSH public key to the Raspberry Pi target account:

```bash
ssh-copy-id "${RPI_USERNAME}@${RPI_ADDRESS}"
```

Verify passwordless SSH access from the development host:

```bash
ssh "${RPI_USERNAME}@${RPI_ADDRESS}" hostname
```

Validation should confirm that SSH login succeeds without interactive password prompts.

### 5. Run automated provisioning

Open the [Python devcontainer](../../.devcontainer/python/), then change to [controller/](../../controller/) and run the provisioning script shown below. The script executes the Ansible workflow that synchronizes the repository and configures the Raspberry Pi runtime environment.

```bash
./scripts/setup_rpi.sh
```

### 6. Run camera service over SSH

After provisioning completes, connect to the Raspberry Pi host and start the camera service from the synchronized repository.

```bash
ssh "${RPI_USERNAME}@${RPI_ADDRESS}"
source ~/venv/bin/activate
cd ~/dust-mite/controller
./scripts/run_camera_stream.sh
```

The service starts a websocket camera stream and keeps running in the active SSH session until interrupted.

From the development host, set `STREAM_CLIENT_URI` to the Raspberry Pi camera websocket endpoint before starting the controller streamer:

```bash
export STREAM_CLIENT_URI="ws://${RPI_ADDRESS}:8765"
```

To persist this value in repository configuration, set `STREAM_CLIENT_URI=ws://<raspberry_pi_hostname_or_ip>:8765` in [.env](../../.env) and reload the shell environment:

```bash
source ./scripts/load_env.sh
```
