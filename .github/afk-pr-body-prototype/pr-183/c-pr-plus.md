Closes #182.

## Summary

Every send of a Camera frame that takes longer than one frame period (40 ms at 25 per second) costs the next Camera frame. Two things made sends that long.

```diff
 stream task, per Camera frame
   take Camera frame
-  send it                     # waits 3–4 rounds of ACKs: 5760 B TCP send buffer, frames up to 26 KB
+  send it                     # queued whole: 32 KB TCP send buffer, segments in PSRAM
 system metrics, per collection
-  uxTaskGetSystemState()      # every 100 ms; masks interrupts, so the camera misses DMA
+  uxTaskGetSystemState()      # every CONFIG_SYSTEM_METRICS_TASK_STATS_REFRESH_MS, default 10 s
```

## Read first

1. [`sdkconfig.defaults` L20–29](https://github.com/ltowarek/dust-mite/blob/010a21ff04b24a3be5673f4b1b49c4b6db0a035a/car/sdkconfig.defaults#L20-L29): five settings, the whole fix for the send.
2. [`system_metrics.cpp` L54–58](https://github.com/ltowarek/dust-mite/blob/010a21ff04b24a3be5673f4b1b49c4b6db0a035a/car/components/tracing/system_metrics.cpp#L54-L58): the refresh gate.

Skim the rest: Kconfig help text and one row of the metrics table.

## Worth understanding

**Why a bigger TCP send buffer raises the frame rate, not only throughput.** The send call returns only once lwIP has accepted every byte. With 5760 bytes of buffer, a 20 KB Camera frame waits for three or four rounds of ACKs over Wi-Fi. Meanwhile the stream task can't take the next Camera frame, and with two frame buffers the camera has nowhere to put one, so it drops it. With 32 KB the whole Camera frame is copied in and the call returns; the ACKs arrive while the camera fills the next buffer.

**Why reading task stats drops Camera frames.** On the dual-core ESP32-S3, `uxTaskGetSystemState()` holds the kernel lock with interrupts masked while it walks every task's stack. The camera's DMA interrupt waits for it, and the frame being captured is lost.

## Evidence

- **Before:** `main`, two runs: 14.4 / 12.5 Camera frames per second; internal free heap at least 104.9 / 97.1 KB while streaming.
  **After:** 17.4 / 17.4 Camera frames per second; internal free heap at least 117.5 / 119.4 KB.
- **CI:** firmware builds with `sdkconfig.defaults`, `.all` and `.profiling`; QEMU tests pass. No QEMU test sees Wi-Fi throughput.

## DUT run

`needs-car`: a QEMU run can't show Wi-Fi sends or DMA interrupts.

Steps, from #182's "How to measure":

- [x] Build `car/` with `SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.all;sdkconfig.defaults.profiling"` and flash it.
- [x] Run `observability/tests/e2e/test_camera_stream.py --dut` twice on `main` and twice on this branch.

Criteria, from #182's "Done when":

- [ ] `test_viewer_receives_camera_rate`, at least 22 per second: **not met**, 17.4. Base64 and cJSON encoding still cap the rate until #104.
- [ ] `test_car_sends_frames_promptly`, send p95 at most 45 ms: **not measured**. The test needs the MJPEG stream from #104.
- [x] Internal free heap does not fall: met, see the table.

_Results from the car agent session, 2026-10-24:_

| | `main` (2 runs) | This PR (2 runs) |
|---|---|---|
| Camera frames per second | 14.4 / 12.5 | 17.4 / 17.4 |
| Gap between Camera frames, p95 | 123 / 136 ms | 119 / 120 ms |
| Internal free heap, idle | 121.4 / 121.8 KB | 123.3 / 123.3 KB |
| Internal free heap, minimum while streaming | 104.9 / 97.1 KB | 117.5 / 119.4 KB |

## Merge Danger

**Door:** two-way

Touches none of the repo's one-way doors: partition table, NVS layout, WebSocket message schema, CI workflows.

**Undo:** revert and flash again; nothing on the car outlives a flash.

**Blast Radius:** internal RAM

The Wi-Fi TX buffers become static. Eight of them and the old RX values keep idle internal RAM where it was in the measured build; builds without `.all` and `.profiling` weren't measured.
