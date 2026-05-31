#!/usr/bin/env bash

set -e

docker compose up --build -d

byobu new-session -d -s dust-mite

# Build 2×2 layout using positional pane references
byobu split-window -h                             # left column / right column
byobu split-window -v -t 'dust-mite:0.{left}'   # top-left / bottom-left
byobu split-window -v -t 'dust-mite:0.{right}'  # top-right / bottom-right

# Top-left: C++ monitor
byobu send-keys -t 'dust-mite:0.{top-left}' \
  'docker compose exec cpp /home/dustmite/run_cpp.sh; exec bash' Enter

# Top-right: Python streamer
byobu send-keys -t 'dust-mite:0.{top-right}' \
  'docker compose exec python /home/dustmite/workspace/controller/scripts/run_streamer.sh; exec bash' Enter

# Bottom-left: JS dev server
byobu send-keys -t 'dust-mite:0.{bottom-left}' \
  'docker compose exec js /home/dustmite/workspace/web/scripts/run_dev_server.sh --port 5173 --host; exec bash' Enter

# Bottom-right: OTel Collector logs
byobu send-keys -t 'dust-mite:0.{bottom-right}' \
  'docker compose logs -f otel-collector' Enter

byobu select-pane -t 'dust-mite:0.{top-left}'

# Stop containers when the session is killed; do nothing on detach.
cleanup() {
    if ! byobu has-session -t dust-mite 2>/dev/null; then
        docker compose down
    fi
}
trap cleanup EXIT

byobu attach-session -t dust-mite
