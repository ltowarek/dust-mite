idf_component_register(SRCS "wifi.cpp"
                    INCLUDE_DIRS "include"
                    PRIV_REQUIRES
                    esp_wifi
                    nvs_flash
                    esp_event
                    esp_netif
                    )
target_compile_definitions(
    ${COMPONENT_LIB}
    PRIVATE
    WIFI_SSID="$ENV{WIFI_SSID}"
    WIFI_PASSWORD="$ENV{WIFI_PASSWORD}"
)
