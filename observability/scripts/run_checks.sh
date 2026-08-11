#!/bin/bash

SCRIPTPATH=$(dirname "$0")

STATUS=0
trap 'STATUS=1' ERR

echo 'run_linters.sh'
$SCRIPTPATH/run_linters.sh
echo 'run_formatter.sh'
$SCRIPTPATH/run_formatter.sh --diff
echo 'run_type_checks.sh'
$SCRIPTPATH/run_type_checks.sh
echo 'run_requirements_checks.sh'
$SCRIPTPATH/run_requirements_checks.sh

trap - ERR

if [ $STATUS -ne 0 ]
then
    echo 'fix_checks.sh'
    $SCRIPTPATH/fix_checks.sh
fi

exit $STATUS
