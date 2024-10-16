#!/bin/bash

pushd ./controller/ > /dev/null
source ./venv/bin/activate

OUTPUT=$(./scripts/run_checks.sh 2>&1)
STATUS=$?

deactivate
popd > /dev/null

if [ $STATUS -ne 0 ]
then
    echo "$OUTPUT"
fi

exit $STATUS
