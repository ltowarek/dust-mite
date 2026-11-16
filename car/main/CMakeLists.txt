idf_component_register(SRCS "main.cpp"
                    INCLUDE_DIRS ""
                    REQUIRES
                    wifi
                    camera
                    web_server
                    motor
                    telemetry
                    tracing
                    )
target_compile_definitions(
    ${COMPONENT_LIB}
    PRIVATE
    CAR_OTLP_TRACES_BASE_URL="$ENV{CAR_OTLP_TRACES_BASE_URL}"
    CAR_OTLP_METRICS_BASE_URL="$ENV{CAR_OTLP_METRICS_BASE_URL}"
    CAR_OTLP_LOGS_BASE_URL="$ENV{CAR_OTLP_LOGS_BASE_URL}"
    CAR_OTLP_PROFILES_BASE_URL="$ENV{CAR_OTLP_PROFILES_BASE_URL}"
)
