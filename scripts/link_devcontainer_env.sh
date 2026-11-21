#!/bin/bash

set -e

cd "$(dirname "${BASH_SOURCE[0]}")/.."

devcontainers=(cpp docs infrastructure js observability python)

for name in "${devcontainers[@]}"; do
    ln -sfn ../../.env ".devcontainer/${name}/.env"
done
