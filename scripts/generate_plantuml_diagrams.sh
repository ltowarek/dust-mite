#!/bin/bash

set -e

PLANTUML_DIR="${1:-./docs/plantuml}"
plantuml -tsvg "$PLANTUML_DIR"/*.puml
