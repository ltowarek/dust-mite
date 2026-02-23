#!/bin/bash

set -e

hidapitester --list-detail
hidapitester --vidpid 054C:0CE6 --open --read-input
