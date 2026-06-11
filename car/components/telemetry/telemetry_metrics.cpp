#include "telemetry_metrics.hpp"
#include "metrics.hpp"
#include "sdkconfig.h"

#ifdef CONFIG_ESP_OPENTELEMETRY_METRICS_ENABLED
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "opentelemetry/metrics/async_instruments.h"
#include "opentelemetry/metrics/provider.h"

namespace metrics_api = opentelemetry::metrics;

namespace {

struct State {
    int   rssi           = 0;
    float speed          = 0.0f;
    int   distance_ahead = 0;
    float accel_x = 0.0f, accel_y = 0.0f, accel_z = 0.0f;
    float mag_x   = 0.0f, mag_y   = 0.0f, mag_z   = 0.0f;
    float gyro_x  = 0.0f, gyro_y  = 0.0f, gyro_z  = 0.0f;
};

static State              s_state;
static SemaphoreHandle_t  s_mutex = NULL;

#define DEFINE_GAUGE_CB(name, expr)                                                         \
    static void cb_##name(opentelemetry::metrics::ObserverResult obs, void*) {              \
        State snap;                                                                         \
        xSemaphoreTake(s_mutex, portMAX_DELAY);                                             \
        snap = s_state;                                                                     \
        xSemaphoreGive(s_mutex);                                                            \
        observe_double(obs, static_cast<double>(snap.expr));                                \
    }

DEFINE_GAUGE_CB(rssi,           rssi)
DEFINE_GAUGE_CB(speed,          speed)
DEFINE_GAUGE_CB(distance_ahead, distance_ahead)
DEFINE_GAUGE_CB(accel_x,        accel_x)
DEFINE_GAUGE_CB(accel_y,        accel_y)
DEFINE_GAUGE_CB(accel_z,        accel_z)
DEFINE_GAUGE_CB(mag_x,          mag_x)
DEFINE_GAUGE_CB(mag_y,          mag_y)
DEFINE_GAUGE_CB(mag_z,          mag_z)
DEFINE_GAUGE_CB(gyro_x,         gyro_x)
DEFINE_GAUGE_CB(gyro_y,         gyro_y)
DEFINE_GAUGE_CB(gyro_z,         gyro_z)

static constexpr size_t kNumInstruments = 12;
static opentelemetry::nostd::shared_ptr<metrics_api::ObservableInstrument> s_instruments[kNumInstruments];

}  // namespace
#endif  // CONFIG_ESP_OPENTELEMETRY_METRICS_ENABLED

void telemetry_metrics_setup() {
#ifdef CONFIG_ESP_OPENTELEMETRY_METRICS_ENABLED
    s_mutex = xSemaphoreCreateMutex();

    auto meter = metrics_api::Provider::GetMeterProvider()->GetMeter(
        CONFIG_ESP_OPENTELEMETRY_SERVICE_NAME, "1.0.0");

    static_assert(kNumInstruments == 12, "Update kNumInstruments when adding or removing instruments");

    s_instruments[0]  = meter->CreateDoubleObservableGauge("dust_mite.rssi",            "WiFi RSSI",      "dBm");
    s_instruments[1]  = meter->CreateDoubleObservableGauge("dust_mite.speed",           "Car speed",      "km/h");
    s_instruments[2]  = meter->CreateDoubleObservableGauge("dust_mite.distance_ahead",  "Ultrasonic distance", "cm");
    s_instruments[3]  = meter->CreateDoubleObservableGauge("dust_mite.accelerometer.x", "Accelerometer X", "g");
    s_instruments[4]  = meter->CreateDoubleObservableGauge("dust_mite.accelerometer.y", "Accelerometer Y", "g");
    s_instruments[5]  = meter->CreateDoubleObservableGauge("dust_mite.accelerometer.z", "Accelerometer Z", "g");
    s_instruments[6]  = meter->CreateDoubleObservableGauge("dust_mite.magnetometer.x",  "Magnetometer X",  "G");
    s_instruments[7]  = meter->CreateDoubleObservableGauge("dust_mite.magnetometer.y",  "Magnetometer Y",  "G");
    s_instruments[8]  = meter->CreateDoubleObservableGauge("dust_mite.magnetometer.z",  "Magnetometer Z",  "G");
    s_instruments[9]  = meter->CreateDoubleObservableGauge("dust_mite.gyroscope.x",     "Gyroscope X",     "deg/s");
    s_instruments[10] = meter->CreateDoubleObservableGauge("dust_mite.gyroscope.y",     "Gyroscope Y",     "deg/s");
    s_instruments[11] = meter->CreateDoubleObservableGauge("dust_mite.gyroscope.z",     "Gyroscope Z",     "deg/s");

    s_instruments[0] ->AddCallback(cb_rssi,           nullptr);
    s_instruments[1] ->AddCallback(cb_speed,          nullptr);
    s_instruments[2] ->AddCallback(cb_distance_ahead, nullptr);
    s_instruments[3] ->AddCallback(cb_accel_x,        nullptr);
    s_instruments[4] ->AddCallback(cb_accel_y,        nullptr);
    s_instruments[5] ->AddCallback(cb_accel_z,        nullptr);
    s_instruments[6] ->AddCallback(cb_mag_x,          nullptr);
    s_instruments[7] ->AddCallback(cb_mag_y,          nullptr);
    s_instruments[8] ->AddCallback(cb_mag_z,          nullptr);
    s_instruments[9] ->AddCallback(cb_gyro_x,         nullptr);
    s_instruments[10]->AddCallback(cb_gyro_y,         nullptr);
    s_instruments[11]->AddCallback(cb_gyro_z,         nullptr);
#endif
}

void telemetry_metrics_update(const telemetry_packet_t& packet) {
#ifdef CONFIG_ESP_OPENTELEMETRY_METRICS_ENABLED
    if (!s_mutex) return;
    xSemaphoreTake(s_mutex, portMAX_DELAY);
    s_state.rssi           = packet.rssi;
    s_state.speed          = packet.speed;
    s_state.distance_ahead = packet.distance_ahead;
    s_state.accel_x        = packet.accelerometer.x;
    s_state.accel_y        = packet.accelerometer.y;
    s_state.accel_z        = packet.accelerometer.z;
    s_state.mag_x          = packet.magnetometer.x;
    s_state.mag_y          = packet.magnetometer.y;
    s_state.mag_z          = packet.magnetometer.z;
    s_state.gyro_x         = packet.gyroscope.x;
    s_state.gyro_y         = packet.gyroscope.y;
    s_state.gyro_z         = packet.gyroscope.z;
    xSemaphoreGive(s_mutex);
#endif
}
