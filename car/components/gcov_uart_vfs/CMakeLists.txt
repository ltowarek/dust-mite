idf_component_register(SRCS "gcov_uart_vfs.c"
                        INCLUDE_DIRS "."
                        PRIV_REQUIRES vfs)

# Compute how many leading path components to strip from the gcda path so
# GCOV_PREFIX=/gcov lands the files relative to the test app root regardless
# of checkout location.  CMAKE_SOURCE_DIR is the test app project root in IDF
# builds.
string(REPLACE "/" ";" _gcov_parts "${CMAKE_SOURCE_DIR}")
list(LENGTH _gcov_parts _gcov_depth)
math(EXPR _gcov_strip "${_gcov_depth} - 1")
idf_component_get_property(lib ${COMPONENT_NAME} COMPONENT_LIB)
target_compile_definitions(${lib} PRIVATE "GCOV_PREFIX_STRIP_COUNT=${_gcov_strip}")
