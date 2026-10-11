#pragma once

#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

// Stand-ins for the car's Wi-Fi, camera and telemetry under QEMU, which emulates an OpenCores
// Ethernet MAC but none of the car's peripherals.
void qemu_ethernet_setup();
// Call after web_server_setup: a queue must be empty when web_server adds it to a queue set.
void qemu_producers_setup(QueueHandle_t frame_queue, QueueHandle_t telemetry_queue);
