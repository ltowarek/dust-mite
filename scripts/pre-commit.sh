#!/bin/bash

pushd ./controller/ > /dev/null
# https://github.com/microsoft/vscode-python/issues/10165
if [[ -z "${VIRTUAL_ENV}" ]]; then
    source /opt/venv/bin/activate
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
