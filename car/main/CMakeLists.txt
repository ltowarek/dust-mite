idf_component_register(SRCS "main.cpp"
                    INCLUDE_DIRS ""
                    REQUIRES
                    camera
                    esp_wifi
                    esp_http_server
                    esp_driver_gpio
                    nvs_flash
                    driver # deprecated
                    )

target_compile_definitions(
    ${COMPONENT_LIB}
    PRIVATE
    WIFI_SSID="$ENV{WIFI_SSID}"
    WIFI_PASSWORD="$ENV{WIFI_PASSWORD}"
)
