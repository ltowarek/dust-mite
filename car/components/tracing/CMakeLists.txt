idf_component_register(SRCS "system_metrics.cpp" "tracing.cpp" "metrics.cpp"
                    INCLUDE_DIRS "include"
                    REQUIRES
                    esp-opentelemetry-cpp
                    cjson
                    pthread
                    heap
                    esp_timer
                    PRIV_REQUIRES
                    esp_driver_tsens
)
