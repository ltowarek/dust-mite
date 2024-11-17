idf_component_register(SRCS "main.cpp"
                    INCLUDE_DIRS ""
                    REQUIRES
                    camera
                    web_server
                    esp_driver_gpio
                    driver # deprecated
                    )
