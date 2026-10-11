set(srcs "main.cpp" "test_command_parser.cpp" "test_web_server.cpp")
if(CONFIG_WEB_SERVER_TEST_QEMU_MODE)
    list(APPEND srcs "qemu_peripherals.cpp")
endif()
idf_component_register(SRCS ${srcs}
                    INCLUDE_DIRS "."
                    PRIV_REQUIRES unity web_server motor tracing wifi telemetry camera driver esp_eth esp_netif
                    WHOLE_ARCHIVE)
