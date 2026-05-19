#!/usr/bin/env bash

set -e

source /home/vscode/venv/bin/activate

# Editable install with egg-info kept outside the mounted workspace.
# Symlinking src/controller (not all of src/) means egg-info is created
# in /tmp/controller-editable/src/ instead of the host-owned workspace tree.
mkdir -p /tmp/controller-editable/src
ln -sfn /workspaces/dust-mite/controller/src/controller /tmp/controller-editable/src/controller
cp /workspaces/dust-mite/controller/pyproject.toml /tmp/controller-editable/
pip install --quiet -e /tmp/controller-editable/

streamer
