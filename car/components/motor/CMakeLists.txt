idf_component_register(SRCS "utils.cpp" "servo.cpp" "motor.cpp"
                    PRIV_INCLUDE_DIRS "private"
                    INCLUDE_DIRS "include"
                    REQUIRES
                    esp_driver_gpio
                    driver # deprecated
                    )
