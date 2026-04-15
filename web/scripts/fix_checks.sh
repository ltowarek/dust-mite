#!/bin/bash

SCRIPTPATH=$(dirname "$0")

$SCRIPTPATH/run_linters.sh --fix
$SCRIPTPATH/run_formatter.sh
