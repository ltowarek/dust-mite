idf_component_register(SRCS "camera.c"
                    INCLUDE_DIRS "include"
                    PRIV_REQUIRES 
                    esp_idf # esp_idf=DFRobot_AXP313A
                    )
