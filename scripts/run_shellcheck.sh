#!/bin/bash

git ls-files -z '*.sh' | xargs -0 shellcheck "$@"
