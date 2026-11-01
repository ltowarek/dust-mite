#!/bin/bash

ENV_FILE="${1:-.env}"

set -a
# shellcheck source=/dev/null # the environment file is generated and untracked
source "${ENV_FILE}"
set +a
