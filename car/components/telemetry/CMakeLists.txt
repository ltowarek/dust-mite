idf_component_register(SRCS "telemetry.cpp" "telemetry_json.cpp"
                    INCLUDE_DIRS "include"
                    REQUIRES
                    esp_netif
                    esp_wifi
                    cjson
                    esp_driver_pcnt
                    esp_timer
                    esp_driver_i2c
                    esp_driver_gpio
                    esp_driver_mcpwm
                    )
