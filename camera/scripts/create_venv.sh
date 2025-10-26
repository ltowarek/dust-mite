#!/bin/bash

set -e

python3 -m venv venv --system-site-packages

source ./venv/bin/activate
python3 -m pip install -r requirements.txt
