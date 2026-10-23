set(srcs "main.cpp" "stream_client.cpp" "test_command_parser.cpp" "test_socket_address.cpp"
         "test_web_server.cpp")
if(CONFIG_WEB_SERVER_TEST_QEMU_MODE)
    list(APPEND srcs "qemu_peripherals.cpp")
else()
    list(APPEND srcs "metrics_collection.cpp" "test_stream_rate.cpp")
    if(CONFIG_ESP_OPENTELEMETRY_PROFILING_ENABLED)
        list(APPEND srcs "profiling_report.cpp")
    endif()
endif()
idf_component_register(SRCS ${srcs}
                    INCLUDE_DIRS "."
                    PRIV_REQUIRES unity esp-opentelemetry-cpp web_server motor tracing wifi telemetry camera driver esp_eth esp_netif esp_event esp_wifi
                    WHOLE_ARCHIVE)
