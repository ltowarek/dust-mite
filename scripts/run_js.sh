#!/usr/bin/env bash

set -e

cd /workspaces/dust-mite/web
npm ci --silent
npx vp dev --port 5173
