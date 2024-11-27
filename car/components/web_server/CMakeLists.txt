idf_component_register(SRCS "web_server.cpp"
                    INCLUDE_DIRS "include"
                    REQUIRES
                    esp_wifi
                    esp_http_server
                    nvs_flash
                    json
                    camera
                    motor
                    )

target_compile_definitions(
    ${COMPONENT_LIB}
    PRIVATE
    WIFI_SSID="$ENV{WIFI_SSID}"
    WIFI_PASSWORD="$ENV{WIFI_PASSWORD}"
)