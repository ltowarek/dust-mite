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

## Differences from the ticket

1. **Not met:** #182's 22 Camera frames per second; this PR reaches 17.4. Base64 and cJSON encoding cap the rate until #104 moves Camera frames to MJPEG; on that branch the same changes reach 24.0. Merge this now, or hold it for #104? See the DUT run under Evidence.
2. **Not asked for:** task stats are read every 10 s instead of every 100 ms, through a new `CONFIG_SYSTEM_METRICS_TASK_STATS_REFRESH_MS`. The DUT run found Camera frames dropped during each read. Task stats stay off unless `sdkconfig.defaults.all`. [`system_metrics.cpp` L54–58](https://github.com/ltowarek/dust-mite/blob/010a21ff04b24a3be5673f4b1b49c4b6db0a035a/car/components/tracing/system_metrics.cpp#L54-L58)
3. **Decided:** eight static Wi-Fi TX buffers and the old RX values. Moving Wi-Fi to PSRAM makes TX buffers static and raises the RX defaults; these counts keep idle internal RAM where it was. [`sdkconfig.defaults` L27–29](https://github.com/ltowarek/dust-mite/blob/010a21ff04b24a3be5673f4b1b49c4b6db0a035a/car/sdkconfig.defaults#L27-L29)
4. **Left out:** #182's candidate 3, a third frame buffer. Candidates 1 and 2 were enough to measure the effect.

Everything else is as #182 asks.

## Worth understanding

<details>
<summary>Why a bigger TCP send buffer raises the frame rate</summary>

The send call returns only once lwIP has accepted every byte. With 5760 bytes of buffer, a 20 KB Camera frame waits for three or four rounds of ACKs over Wi-Fi. Meanwhile the stream task can't take the next Camera frame, and with two frame buffers the camera has nowhere to put one, so it drops it. With 32 KB the whole Camera frame is copied in and the call returns; the ACKs arrive while the camera fills the next buffer.

</details>

<details>
<summary>Why reading task stats drops Camera frames</summary>

On the dual-core ESP32-S3, `uxTaskGetSystemState()` holds the kernel lock with interrupts masked while it walks every task's stack. The camera's DMA interrupt waits for it, and the frame being captured is lost.

</details>

## Evidence

### DUT run

_Car agent session, 2026-10-24: `sdkconfig.defaults` + `.all` + `.profiling`, two runs on `main` and two on this branch._

| | `main` | This PR | #182 asks |
|---|---|---|---|
| Camera frames per second | 14.4 / 12.5 | 17.4 / 17.4 | at least 22: **not met** |
| Send p95 | | | at most 45 ms: **not measured**, the test needs #104 |
| Internal free heap, minimum while streaming | 104.9 / 97.1 KB | 117.5 / 119.4 KB | no fall: met |
| Internal free heap, idle | 121.4 / 121.8 KB | 123.3 / 123.3 KB | |
| Gap between Camera frames, p95 | 123 / 136 ms | 119 / 120 ms | |

<details>
<summary>Steps, from #182's "How to measure"</summary>

- [x] Build `car/` with `SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.all;sdkconfig.defaults.profiling"` and flash it.
- [x] Run `observability/tests/e2e/test_camera_stream.py --dut` twice on `main` and twice on this branch.

</details>

### CI

Firmware builds with `sdkconfig.defaults`, `.all` and `.profiling`; QEMU tests pass. No QEMU test sees Wi-Fi sends or DMA interrupts.

## Merge Danger

**Door:** two-way

**Blast Radius:** internal RAM

The Wi-Fi TX buffers become static. Eight of them and the old RX values keep idle internal RAM where it was in the measured build; builds without `.all` and `.profiling` weren't measured.

---

🤖 Written by an [AFK run](https://github.com/ltowarek/dust-mite/actions) (example link).
