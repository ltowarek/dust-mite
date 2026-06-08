idf_component_register(SRCS "web_server_metrics.cpp" "web_server.cpp" "command_parser.cpp"
                    INCLUDE_DIRS "include"
                    REQUIRES
                    esp-opentelemetry-cpp
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
