#!/bin/bash

set -e

hidapitester --list
hidapitester --vidpid 054C:0CE6 --open --read-input
