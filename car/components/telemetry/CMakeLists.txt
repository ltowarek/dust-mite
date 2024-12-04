idf_component_register(SRCS "telemetry.cpp"
                    INCLUDE_DIRS "include"
                    REQUIRES
                    esp_netif
                    esp_wifi
                    json
                    )
