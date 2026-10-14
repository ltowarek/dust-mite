#include "qemu_peripherals.hpp"
#include <cstdio>
#include "esp_camera.h"
#include "esp_eth.h"
#include "esp_eth_mac_openeth.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "freertos/task.h"
#include "telemetry_types.hpp"

void qemu_ethernet_setup() {
  ESP_ERROR_CHECK(esp_netif_init());
  ESP_ERROR_CHECK(esp_event_loop_create_default());
  esp_netif_config_t netif_cfg = ESP_NETIF_DEFAULT_ETH();
  esp_netif_t* netif = esp_netif_new(&netif_cfg);

  eth_mac_config_t mac_cfg = ETH_MAC_DEFAULT_CONFIG();
  eth_phy_config_t phy_cfg = ETH_PHY_DEFAULT_CONFIG();
  phy_cfg.autonego_timeout_ms = 100;
  esp_eth_config_t eth_cfg =
      ETH_DEFAULT_CONFIG(esp_eth_mac_new_openeth(&mac_cfg), esp_eth_phy_new_generic(&phy_cfg));
  esp_eth_handle_t eth = nullptr;
  ESP_ERROR_CHECK(esp_eth_driver_install(&eth_cfg, &eth));
  ESP_ERROR_CHECK(esp_netif_attach(netif, esp_eth_new_netif_glue(eth)));
  ESP_ERROR_CHECK(esp_eth_start(eth));
}

static uint8_t g_frame_data[] = {0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0xFF, 0xD9};
static camera_fb_t g_frame = {};

static void camera_stub_task(void* p) {
  auto frame_queue = static_cast<QueueHandle_t>(p);
  g_frame.buf = g_frame_data;
  g_frame.len = sizeof(g_frame_data);
  g_frame.format = PIXFORMAT_JPEG;
  camera_fb_t* frame = &g_frame;
  for (int i = 0;; ++i) {
    xQueueSend(frame_queue, &frame, portMAX_DELAY);
    vTaskDelay(pdMS_TO_TICKS(50));
  }
}

static void telemetry_stub_task(void* p) {
  auto telemetry_queue = static_cast<QueueHandle_t>(p);
  for (int i = 0;; ++i) {
    telemetry_packet_t packet = {};
    snprintf(packet.timestamp, sizeof(packet.timestamp), "1970-01-01T00:00:00Z");
    packet.distance_ahead = i;
    xQueueSend(telemetry_queue, &packet, 0);
    vTaskDelay(pdMS_TO_TICKS(500));
  }
}

void qemu_producers_setup(QueueHandle_t frame_queue, QueueHandle_t telemetry_queue) {
  xTaskCreate(camera_stub_task, "camera_stub", 3072, frame_queue, 1, nullptr);
  xTaskCreate(telemetry_stub_task, "telemetry_stub", 3072, telemetry_queue, 1, nullptr);
}
