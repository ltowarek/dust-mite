idf_component_register(SRCS "motor.cpp"
                    INCLUDE_DIRS "include"
                    REQUIRES
                    esp_driver_gpio
                    driver # deprecated
                    )
