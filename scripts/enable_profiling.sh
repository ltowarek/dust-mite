#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

source scripts/load_env.sh
PROFILING_ENABLED=1 ./scripts/dump_env.sh
