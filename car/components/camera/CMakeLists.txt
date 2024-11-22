idf_component_register(SRCS "camera.cpp"
                    INCLUDE_DIRS "include"
                    PRIV_REQUIRES 
                    esp_idf # esp_idf=DFRobot_AXP313A
                    )
