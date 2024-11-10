#!/bin/bash

pushd ./controller/ > /dev/null
if [[ -z "${VIRTUAL_ENV}" ]]; then
    if [ ! -d "./venv/" ]; then
        ./scripts/create_venv.sh > /dev/null
    fi
    source ./venv/bin/activate
fi

OUTPUT=$(./scripts/run_checks.sh 2>&1)
STATUS=$?

deactivate
popd > /dev/null

if [ $STATUS -ne 0 ]
then
    echo "$OUTPUT"
fi

exit $STATUS
