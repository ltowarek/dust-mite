#pragma once

#ifdef __cplusplus
extern "C" {
#endif
#include "esp_camera.h"

void camera_setup(void);
camera_fb_t* camera_fb_get(void);
void camera_fb_return(camera_fb_t *fb);

#ifdef __cplusplus
}
#endif
