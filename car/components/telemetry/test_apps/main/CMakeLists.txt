set(srcs "main.cpp" "test_telemetry_json.cpp")
if(NOT CONFIG_TELEMETRY_TEST_QEMU_MODE)
    list(APPEND srcs "test_telemetry.cpp")
endif()

idf_component_register(SRCS ${srcs}
                    INCLUDE_DIRS "."
                    PRIV_REQUIRES unity telemetry
                    WHOLE_ARCHIVE)
