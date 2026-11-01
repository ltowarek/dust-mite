#!/bin/bash

set -e

gh extension install github/gh-actions-lock --pin v0.4.0
gh actions-lock "$@"
