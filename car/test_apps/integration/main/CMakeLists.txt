idf_component_register(SRCS "main.cpp"
                    INCLUDE_DIRS "."
                    PRIV_REQUIRES
                    motor wifi tracing camera telemetry web_server
                    esp_driver_i2c)
