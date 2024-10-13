#!/bin/bash

set -e

if [ ! -f /tmp/hidapitester ]; then
    echo "hidapitester not found!"
    wget https://github.com/todbot/hidapitester/releases/download/v0.5/hidapitester-linux-x86_64.zip
    unzip hidapitester-linux-x86_64.zip
    mv ./hidapitester /tmp/hidapitester
    rm hidapitester-linux-x86_64.zip
fi 

/tmp/hidapitester --list
/tmp/hidapitester --vidpid 054C:0CE6 --open --read-input
