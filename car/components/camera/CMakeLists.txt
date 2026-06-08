idf_component_register(SRCS "camera_metrics.cpp" "camera.cpp"
                    INCLUDE_DIRS "include"
                    REQUIRES
                    esp_driver_i2c
                    PRIV_REQUIRES
                    esp_idf # esp_idf=DFRobot_AXP313A
                    esp-opentelemetry-cpp
                    tracing
                    )
