#!/bin/bash

SCRIPTPATH=$(dirname "$0")

$SCRIPTPATH/run_linters.sh --fix --silent
$SCRIPTPATH/run_formatter.sh --silent
