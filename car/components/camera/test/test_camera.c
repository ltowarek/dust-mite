#include "stdio.h"
#include "camera.h"
#include "unity.h"
#include "esp_timer.h"


TEST_CASE("performance", "[camera]")
{
    camera_setup();

    const unsigned MEASUREMENTS = 100;

    uint64_t start = esp_timer_get_time();
    for (int i = 0; i < MEASUREMENTS; i++) {
        camera_fb_t * frame = camera_fb_get();
        camera_fb_return(frame);
    }
    uint64_t end = esp_timer_get_time();

    uint64_t duration_s = (end-start)/1000000;

    printf("%u iterations took %llu seconds (%llu frames per second)\n",
           MEASUREMENTS, duration_s, MEASUREMENTS/duration_s);
}
