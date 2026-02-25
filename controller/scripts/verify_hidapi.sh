#!/bin/bash

set -e

hidapitester --list
hidapitester --open-path "$CONTROLLER_DEVICE" --read-input
