#!/bin/bash

SCRIPTPATH=$(dirname "$0")

"$SCRIPTPATH/run_shfmt.sh" --write
"$SCRIPTPATH/run_zizmor.sh" --fix
