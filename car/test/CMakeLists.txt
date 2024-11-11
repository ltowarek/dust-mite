cmake_minimum_required(VERSION 3.16)

set(EXTRA_COMPONENT_DIRS "../components" "../components/DFRobot_AXP313A/DFRobot_AXP313A/esp_idf")

set(TEST_COMPONENTS "camera" CACHE STRING "List of components to test")

# Have to be separate project due to:
# - https://github.com/espressif/esp-idf/issues/3640
# - https://www.esp32.com/viewtopic.php?t=36366
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(hello_world_test)
