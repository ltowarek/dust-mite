#!/bin/bash

OUTPUT=$(./scripts/run_infrastructure_checks.sh 2>&1)
STATUS=$?

if [ $STATUS -ne 0 ]; then
    echo "$OUTPUT"
fi

exit $STATUS
