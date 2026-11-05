#!/bin/bash

git ls-files -z '*.yml' '*.yaml' | xargs -0 yamllint --strict "$@"
