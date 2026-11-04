#!/bin/bash

SCRIPTPATH=$(dirname "$0")

STATUS=0
trap 'STATUS=1' ERR

echo 'run_actionlint.sh'
"$SCRIPTPATH/run_actionlint.sh"

trap - ERR

if [ $STATUS -ne 0 ]
then
    echo 'fix_infrastructure_checks.sh'
    "$SCRIPTPATH/fix_infrastructure_checks.sh"
fi

exit $STATUS
