#!/bin/bash

SCRIPTPATH=$(dirname "$0")

STATUS=0
trap 'STATUS=1' ERR

echo 'run_clang_format.sh'
$SCRIPTPATH/run_clang_format.sh -n --Werror

trap - ERR

if [ $STATUS -ne 0 ]
then
    echo 'fix_checks.sh'
    $SCRIPTPATH/fix_checks.sh
fi

trap 'STATUS=1' ERR

echo 'run_clang_tidy.sh'
$SCRIPTPATH/run_clang_tidy.sh

trap - ERR

exit $STATUS
