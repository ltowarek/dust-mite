#!/bin/bash

SCRIPTPATH=$(dirname "${BASH_SOURCE[0]}")

OUTPUT=$("$SCRIPTPATH"/run_checks.sh 2>&1)
STATUS=$?

if [ $STATUS -ne 0 ]
then
    echo "$OUTPUT"
fi

exit $STATUS
