#include "wifi.hpp"
#include "esp_wifi.h"
#include "nvs_flash.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include <string.h>

static const char* TAG = "wifi";

static EventGroupHandle_t s_wifi_events;
#define WIFI_IP_READY_BIT BIT0

#ifndef WIFI_SSID
#define WIFI_SSID "<SSID>"
#endif
#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD "<PASSWORD>"
#endif

static void wifi_event_handler(void* arg, esp_event_base_t event_base,
                               int32_t event_id, void* event_data)
{
  if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
    esp_wifi_connect();
  } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
    ESP_LOGI(TAG, "retrying connection to AP");
    esp_wifi_connect();
  } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
    xEventGroupSetBits(s_wifi_events, WIFI_IP_READY_BIT);
  }
}

void wifi_wait_for_ip() {
  xEventGroupWaitBits(s_wifi_events, WIFI_IP_READY_BIT, pdFALSE, pdFALSE, portMAX_DELAY);
}

void wifi_setup()
{
  s_wifi_events = xEventGroupCreate();
  ESP_ERROR_CHECK(nvs_flash_init());
  ESP_ERROR_CHECK(esp_netif_init());
  ESP_ERROR_CHECK(esp_event_loop_create_default());
  esp_netif_create_default_wifi_sta();

  wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
  ESP_ERROR_CHECK(esp_wifi_init(&cfg));

  ESP_ERROR_CHECK(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL, NULL));
  ESP_ERROR_CHECK(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL, NULL));

  wifi_config_t wifi_config = {};
  strcpy((char*)wifi_config.sta.ssid, WIFI_SSID);
  strcpy((char*)wifi_config.sta.password, WIFI_PASSWORD);
  wifi_config.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;

  ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
  ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
  ESP_ERROR_CHECK(esp_wifi_start());

  ESP_LOGI(TAG, "wifi_init_sta finished.");
}
