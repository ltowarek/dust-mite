#!/bin/bash

set -e

# Create or truncate the temp env file so stale values are removed on each run.
: > .env.tmp

declare -A ENV_MAP

ENV_MAP[RPI_ADDRESS]=${RPI_ADDRESS:-192.168.50.16}
ENV_MAP[RPI_USERNAME]=${RPI_USERNAME:-pi}
ENV_MAP[ESP32_ADDRESS]=${ESP32_ADDRESS:-ws://192.168.50.66}
ENV_MAP[ESP32_DEVICE]=${ESP32_DEVICE:-/dev/ttyACM0}

ENV_MAP[WIFI_SSID]=${WIFI_SSID:-foo}
ENV_MAP[WIFI_PASSWORD]=${WIFI_PASSWORD:-bar}

ENV_MAP[TELEMETRY_CLIENT_URI]="${ENV_MAP[ESP32_ADDRESS]}/telemetry"
ENV_MAP[CONTROLLER_CLIENT_URI]="${ENV_MAP[ESP32_ADDRESS]}"
ENV_MAP[STREAM_CLIENT_URI]="${ENV_MAP[ESP32_ADDRESS]}/stream"

ENV_MAP[OTEL_EXPORTER_OTLP_ENDPOINT]=${OTEL_EXPORTER_OTLP_ENDPOINT:-http://jaeger:4318}

# Iterate all env entries by sorted key so .env output is deterministic.
while IFS= read -r key; do
	printf '%s=%s\n' "$key" "${ENV_MAP[$key]}" >> .env.tmp
done < <(printf '%s\n' "${!ENV_MAP[@]}" | sort)

mv .env.tmp .env
