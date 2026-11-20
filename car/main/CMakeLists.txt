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
    CAR_OTEL_EXPORTER_OTLP_TRACES_ENDPOINT="$ENV{CAR_OTEL_EXPORTER_OTLP_TRACES_ENDPOINT}"
    CAR_OTEL_EXPORTER_OTLP_METRICS_ENDPOINT="$ENV{CAR_OTEL_EXPORTER_OTLP_METRICS_ENDPOINT}"
    CAR_OTEL_EXPORTER_OTLP_LOGS_ENDPOINT="$ENV{CAR_OTEL_EXPORTER_OTLP_LOGS_ENDPOINT}"
    CAR_OTEL_EXPORTER_OTLP_PROFILES_ENDPOINT="$ENV{CAR_OTEL_EXPORTER_OTLP_PROFILES_ENDPOINT}"
)
