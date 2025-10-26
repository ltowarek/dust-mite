#!/bin/bash

set -e

pip-compile-multi --upgrade-package $1
