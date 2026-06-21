#!/bin/bash

SCRIPTPATH=$(dirname "$0")

STATUS=0
trap 'STATUS=1' ERR

echo 'run_formatter.sh'
$SCRIPTPATH/run_formatter.sh -n --Werror

trap - ERR

if [ $STATUS -ne 0 ]
then
    echo 'fix_checks.sh'
    $SCRIPTPATH/fix_checks.sh
fi

trap 'STATUS=1' ERR

echo 'run_static_analysis.sh'
$SCRIPTPATH/run_static_analysis.sh

trap - ERR

exit $STATUS
