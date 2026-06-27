cmake_minimum_required(VERSION 3.16)
set(EXTRA_COMPONENT_DIRS "../.." "../../DFRobot_AXP313A/DFRobot_AXP313A/esp_idf")
set(COMPONENTS main)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(web_server_test)

# Opt-in via CONFIG_WEB_SERVER_TEST_UBSAN (see CONTRIBUTING.md); scoped to the
# component under test since enabling UBSan project-wide grows code/data size
# too much to fit on-target.
if(CONFIG_WEB_SERVER_TEST_UBSAN)
    idf_component_get_property(web_server_lib web_server COMPONENT_LIB)
    target_compile_options(${web_server_lib} PRIVATE "-fsanitize=undefined" "-fno-sanitize=shift-base")
endif()

# Opt-in via CONFIG_WEB_SERVER_TEST_COVERAGE (see CONTRIBUTING.md); scoped to
# the component under test.
if(CONFIG_WEB_SERVER_TEST_COVERAGE)
    idf_component_get_property(web_server_lib web_server COMPONENT_LIB)
    target_compile_options(${web_server_lib} PRIVATE "--coverage")

    # --coverage on the link step lets g++ pick the right libgcov multilib
    # variant; -lgcov alone does not resolve the correct esp32s3 multilib path.
    target_link_options(${CMAKE_PROJECT_NAME}.elf PRIVATE "--coverage")
endif()
