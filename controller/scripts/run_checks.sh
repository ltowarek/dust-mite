#!/bin/bash

set -e

SCRIPTPATH=$(dirname "$0")

set -x
$SCRIPTPATH/run_linters.sh --fix
$SCRIPTPATH/run_formatter.sh
$SCRIPTPATH/run_type_checks.sh
$SCRIPTPATH/run_requirements_checks.sh
