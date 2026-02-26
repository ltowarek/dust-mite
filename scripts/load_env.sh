#!/bin/bash

ENV_FILE="${1:-.env}"

set -a
source "${ENV_FILE}"
set +a
