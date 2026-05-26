idf_component_register(SRCS "tracing.cpp"
                    INCLUDE_DIRS "include"
                    REQUIRES
                    esp-opentelemetry-cpp
                    cjson
                    pthread
                    )
