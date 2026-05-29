#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "web_server.hpp"
#include "motor.hpp"
#include "tracing.hpp"
#include "wifi.hpp"
#include "telemetry.hpp"

extern "C" void app_main(void)
{
    QueueHandle_t command_queue   = xQueueCreate(2, sizeof(command_packet_t));
    QueueHandle_t frame_queue     = xQueueCreate(2, sizeof(void*));
    QueueHandle_t telemetry_queue = xQueueCreate(2, sizeof(telemetry_packet_t));

    motor_setup(command_queue);
    tracing_setup();
    wifi_setup();
    web_server_setup(frame_queue, command_queue, telemetry_queue);
}
