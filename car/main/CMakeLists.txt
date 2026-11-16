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
    CAR_OTLP_HOST="$ENV{CAR_OTLP_HOST}"
)
