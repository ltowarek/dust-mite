#include "stdio.h"
#include "camera.hpp"
#include "unity.h"
#include "esp_timer.h"
#include "esp_camera.h"


int is_initialized = 0;

void setUp(void)
{
    if (is_initialized == 0) {
        camera_init();
        is_initialized = 1;
    }
}

void tearDown(void)
{
}

TEST_CASE("performance", "[camera]")
{

    const unsigned MEASUREMENTS = 100;

    uint64_t start = esp_timer_get_time();
    for (int i = 0; i < MEASUREMENTS; i++) {
        camera_fb_t * frame = esp_camera_fb_get();
        esp_camera_fb_return(frame);
    }
    uint64_t end = esp_timer_get_time();

    uint64_t duration_s = (end-start)/1000000;
    uint64_t fps = MEASUREMENTS/duration_s;

    printf("%u iterations took %llu seconds (%llu frames per second)\n",
           MEASUREMENTS, duration_s, fps);

    TEST_ASSERT(fps == 25);
}


TEST_CASE("throughput", "[camera]")
{
    const unsigned MEASUREMENTS = 100;

    size_t frame_sizes = 0;

    uint64_t start = esp_timer_get_time();
    for (int i = 0; i < MEASUREMENTS; i++) {
        camera_fb_t * frame = esp_camera_fb_get();
        frame_sizes += frame->len;
        esp_camera_fb_return(frame);
    }
    uint64_t end = esp_timer_get_time();

    uint64_t duration_s = (end-start)/1000000;
    uint64_t throughput_mbps = frame_sizes/duration_s*8/1000000;

    printf("%u iterations took %llu seconds with total frame size of %zu bytes (%llu MBit/s)\n",
           MEASUREMENTS, duration_s, frame_sizes, throughput_mbps);

    TEST_ASSERT(throughput_mbps == 6);
}
