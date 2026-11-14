#!/bin/bash

git ls-files -z 'Dockerfile' '*/Dockerfile' | xargs -0 hadolint "$@"
