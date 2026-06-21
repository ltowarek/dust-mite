#include "system_metrics.hpp"
#include "metrics.hpp"
#include "sdkconfig.h"

#ifdef CONFIG_ESP_OPENTELEMETRY_METRICS_ENABLED
#include "driver/temperature_sensor.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/idf_additions.h"
#include "freertos/task.h"
#include "opentelemetry/common/key_value_iterable_view.h"
#include "opentelemetry/metrics/async_instruments.h"
#include "opentelemetry/metrics/observer_result.h"
#include "opentelemetry/metrics/provider.h"
#include "opentelemetry/nostd/shared_ptr.h"
#include "opentelemetry/nostd/variant.h"
#include <array>
#include <cassert>

namespace metrics_api = opentelemetry::metrics;

namespace {

static temperature_sensor_handle_t s_temp_sensor = NULL;

#ifdef CONFIG_ESP_OPENTELEMETRY_METRICS_TASK_STATS_ENABLED
static constexpr UBaseType_t kMaxTasks = 48;

struct TaskStat {
    TaskHandle_t handle        = nullptr;
    char         name[configMAX_TASK_NAME_LEN + 1] = {};
    char         core[4]       = {};
    uint32_t     prev_run_time = 0;
    UBaseType_t  priority      = 0;
    float        cpu_pct       = 0.0f;
};
static TaskStat    s_task_stats[kMaxTasks];
static UBaseType_t s_task_count      = 0;
static int64_t     s_prev_sample_time  = 0;
static int64_t     s_last_refresh_time = 0;

template <typename T>
static void observe_task_metric(opentelemetry::metrics::ObserverResult& obs,
                                T value, const char* task_name, const char* core) {
    using Pair = std::pair<opentelemetry::nostd::string_view,
                           opentelemetry::common::AttributeValue>;
    std::array<Pair, 2> attrs{{
        {"task", opentelemetry::nostd::string_view(task_name)},
        {"core", opentelemetry::nostd::string_view(core)}
    }};
    opentelemetry::nostd::get<
        opentelemetry::nostd::shared_ptr<opentelemetry::metrics::ObserverResultT<T>>>(obs)
        ->Observe(value, opentelemetry::common::KeyValueIterableView<std::array<Pair, 2>>(attrs));
}

static void refresh_task_stats() {
    int64_t now = esp_timer_get_time();
    if (now - s_last_refresh_time < 100000LL) return;

    static TaskStatus_t snap[kMaxTasks];
    uint32_t dummy;
    UBaseType_t n = uxTaskGetSystemState(snap, kMaxTasks, &dummy);
    if (n == 0) return;

    s_last_refresh_time = now;
    int64_t dt = now - s_prev_sample_time;

    for (UBaseType_t i = 0; i < n; i++) {
        float pct = 0.0f;
        if (s_prev_sample_time > 0 && dt > 0) {
            for (UBaseType_t j = 0; j < s_task_count; j++) {
                if (s_task_stats[j].handle == snap[i].xHandle) {
                    uint32_t delta = snap[i].ulRunTimeCounter - s_task_stats[j].prev_run_time;
                    pct = (static_cast<float>(delta) / static_cast<float>(dt)) * 100.0f;
                    if (pct < 0.0f) pct = 0.0f;
                    if (pct > 100.0f) pct = 100.0f;
                    break;
                }
            }
        }
        BaseType_t core_id = xTaskGetCoreID(snap[i].xHandle);
        if (core_id == tskNO_AFFINITY) {
            s_task_stats[i].core[0] = 'a'; s_task_stats[i].core[1] = 'n';
            s_task_stats[i].core[2] = 'y'; s_task_stats[i].core[3] = '\0';
        } else {
            s_task_stats[i].core[0] = '0' + static_cast<char>(core_id);
            s_task_stats[i].core[1] = '\0';
        }
        s_task_stats[i].handle        = snap[i].xHandle;
        strncpy(s_task_stats[i].name, snap[i].pcTaskName, configMAX_TASK_NAME_LEN);
        s_task_stats[i].name[configMAX_TASK_NAME_LEN] = '\0';
        s_task_stats[i].prev_run_time = snap[i].ulRunTimeCounter;
        s_task_stats[i].priority      = snap[i].uxCurrentPriority;
        s_task_stats[i].cpu_pct       = pct;
    }
    s_task_count       = n;
    s_prev_sample_time = now;
}
#endif  // CONFIG_ESP_OPENTELEMETRY_METRICS_TASK_STATS_ENABLED

static void cb_free_heap(opentelemetry::metrics::ObserverResult obs, void*) {
    observe_int64(obs, static_cast<int64_t>(esp_get_free_heap_size()));
}
static void cb_min_free_heap(opentelemetry::metrics::ObserverResult obs, void*) {
    observe_int64(obs, static_cast<int64_t>(esp_get_minimum_free_heap_size()));
}
#ifdef CONFIG_ESP_OPENTELEMETRY_METRICS_LARGEST_FREE_BLOCK_ENABLED
static void cb_largest_free_block(opentelemetry::metrics::ObserverResult obs, void*) {
    observe_int64(obs, static_cast<int64_t>(heap_caps_get_largest_free_block(MALLOC_CAP_8BIT)));
}
#endif  // CONFIG_ESP_OPENTELEMETRY_METRICS_LARGEST_FREE_BLOCK_ENABLED
static void cb_internal_free_heap(opentelemetry::metrics::ObserverResult obs, void*) {
    observe_int64(obs, static_cast<int64_t>(esp_get_free_internal_heap_size()));
}
static void cb_free_psram(opentelemetry::metrics::ObserverResult obs, void*) {
    observe_int64(obs, static_cast<int64_t>(heap_caps_get_free_size(MALLOC_CAP_SPIRAM)));
}
static void cb_uptime(opentelemetry::metrics::ObserverResult obs, void*) {
    observe_double(obs, static_cast<double>(esp_timer_get_time()) / 1e6);
}
static void cb_temperature(opentelemetry::metrics::ObserverResult obs, void*) {
    float temp = 0.0f;
    if (s_temp_sensor) temperature_sensor_get_celsius(s_temp_sensor, &temp);
    observe_double(obs, static_cast<double>(temp));
}
#ifdef CONFIG_ESP_OPENTELEMETRY_METRICS_TASK_STATS_ENABLED
static void cb_task_cpu_usage(opentelemetry::metrics::ObserverResult obs, void*) {
    refresh_task_stats();
    for (UBaseType_t i = 0; i < s_task_count; i++)
        observe_task_metric(obs, static_cast<double>(s_task_stats[i].cpu_pct),
                            s_task_stats[i].name, s_task_stats[i].core);
}
static void cb_task_priority(opentelemetry::metrics::ObserverResult obs, void*) {
    refresh_task_stats();
    for (UBaseType_t i = 0; i < s_task_count; i++)
        observe_task_metric(obs, static_cast<int64_t>(s_task_stats[i].priority),
                            s_task_stats[i].name, s_task_stats[i].core);
}
#endif  // CONFIG_ESP_OPENTELEMETRY_METRICS_TASK_STATS_ENABLED

// Base instruments (free heap, min free heap, internal free heap, free psram,
// uptime, temperature) plus whichever of the two debug-only, opt-in groups
// below are enabled.
static constexpr size_t kBaseInstruments = 6;
#ifdef CONFIG_ESP_OPENTELEMETRY_METRICS_LARGEST_FREE_BLOCK_ENABLED
static constexpr size_t kLargestFreeBlockInstruments = 1;
#else
static constexpr size_t kLargestFreeBlockInstruments = 0;
#endif
#ifdef CONFIG_ESP_OPENTELEMETRY_METRICS_TASK_STATS_ENABLED
static constexpr size_t kTaskStatsInstruments = 2;
#else
static constexpr size_t kTaskStatsInstruments = 0;
#endif
static constexpr size_t kNumInstruments =
    kBaseInstruments + kLargestFreeBlockInstruments + kTaskStatsInstruments;
static opentelemetry::nostd::shared_ptr<metrics_api::ObservableInstrument> s_instruments[kNumInstruments];

}  // namespace
#endif  // CONFIG_ESP_OPENTELEMETRY_METRICS_ENABLED

void system_metrics_setup() {
#ifdef CONFIG_ESP_OPENTELEMETRY_METRICS_ENABLED
    temperature_sensor_config_t temp_cfg = TEMPERATURE_SENSOR_CONFIG_DEFAULT(10, 80);
    temperature_sensor_install(&temp_cfg, &s_temp_sensor);
    temperature_sensor_enable(s_temp_sensor);

    auto meter = metrics_api::Provider::GetMeterProvider()->GetMeter(
        CONFIG_ESP_OPENTELEMETRY_SERVICE_NAME, "1.0.0");

    size_t idx = 0;

    s_instruments[idx] = meter->CreateInt64ObservableGauge("dust_mite.free_heap_bytes",        "Free heap",                          "By");
    s_instruments[idx]->AddCallback(cb_free_heap, nullptr);
    idx++;

    s_instruments[idx] = meter->CreateInt64ObservableGauge("dust_mite.min_free_heap_bytes",     "Min free heap since boot",           "By");
    s_instruments[idx]->AddCallback(cb_min_free_heap, nullptr);
    idx++;

#ifdef CONFIG_ESP_OPENTELEMETRY_METRICS_LARGEST_FREE_BLOCK_ENABLED
    s_instruments[idx] = meter->CreateInt64ObservableGauge("dust_mite.largest_free_block_bytes", "Largest contiguous free heap block", "By");
    s_instruments[idx]->AddCallback(cb_largest_free_block, nullptr);
    idx++;
#endif

    s_instruments[idx] = meter->CreateInt64ObservableGauge("dust_mite.internal_free_heap_bytes", "Free internal SRAM heap",           "By");
    s_instruments[idx]->AddCallback(cb_internal_free_heap, nullptr);
    idx++;

    s_instruments[idx] = meter->CreateInt64ObservableGauge("dust_mite.free_psram_bytes",        "Free PSRAM",                         "By");
    s_instruments[idx]->AddCallback(cb_free_psram, nullptr);
    idx++;

    s_instruments[idx] = meter->CreateDoubleObservableGauge("dust_mite.uptime",                  "Uptime since boot",                  "s");
    s_instruments[idx]->AddCallback(cb_uptime, nullptr);
    idx++;

    s_instruments[idx] = meter->CreateDoubleObservableGauge("dust_mite.temperature",             "Die temperature",                    "Cel");
    s_instruments[idx]->AddCallback(cb_temperature, nullptr);
    idx++;

#ifdef CONFIG_ESP_OPENTELEMETRY_METRICS_TASK_STATS_ENABLED
    s_instruments[idx] = meter->CreateDoubleObservableGauge("dust_mite.task_cpu_usage",          "Per-task CPU usage",                 "%");
    s_instruments[idx]->AddCallback(cb_task_cpu_usage, nullptr);
    idx++;

    s_instruments[idx] = meter->CreateInt64ObservableGauge("dust_mite.task_priority",            "Per-task FreeRTOS priority",         "1");
    s_instruments[idx]->AddCallback(cb_task_priority, nullptr);
    idx++;
#endif

    assert(idx == kNumInstruments);
#endif
}
