cmake_minimum_required(VERSION 3.16)

set(EXTRA_COMPONENT_DIRS "../.." "../../DFRobot_AXP313A/DFRobot_AXP313A/esp_idf")
set(COMPONENTS main)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(telemetry_test)

# Scope UBSan to the component under test (see CONTRIBUTING.md); enabling it
# project-wide grows code/data size too much to fit on-target.
idf_component_get_property(telemetry_lib telemetry COMPONENT_LIB)
target_compile_options(${telemetry_lib} PRIVATE "-fsanitize=undefined" "-fno-sanitize=shift-base")