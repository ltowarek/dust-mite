cmake_minimum_required(VERSION 3.16)

set(EXTRA_COMPONENT_DIRS "./components/DFRobot_AXP313A/DFRobot_AXP313A/esp_idf")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(hello_world)
