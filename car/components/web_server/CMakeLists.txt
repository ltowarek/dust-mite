idf_component_register(SRCS "web_server.cpp"
                    INCLUDE_DIRS "include"
                    REQUIRES
                    wifi
                    esp_wifi
                    esp_http_server
                    cjson
                    mbedtls
                    camera
                    motor
                    telemetry
                    tracing
                    )
