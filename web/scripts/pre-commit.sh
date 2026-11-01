#!/bin/bash

pushd ./web/ >/dev/null || exit

OUTPUT=$(./scripts/run_checks.sh 2>&1)
STATUS=$?

popd >/dev/null || exit

if [ $STATUS -ne 0 ]; then
    echo "$OUTPUT"
fi

exit $STATUS
