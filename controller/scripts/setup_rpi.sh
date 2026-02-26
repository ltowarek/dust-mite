#!/bin/bash

set -e

cd ansible

ansible-playbook \
	-i "${RPI_ADDRESS}," \
	-u "${RPI_USERNAME}" \
	setup_rpi.yml
