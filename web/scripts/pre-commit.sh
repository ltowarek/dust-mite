#!/bin/bash

pushd ./web/ > /dev/null

OUTPUT=$(./scripts/run_checks.sh 2>&1)
STATUS=$?

popd > /dev/null

if [ $STATUS -ne 0 ]
then
    echo "$OUTPUT"
fi

exit $STATUS
