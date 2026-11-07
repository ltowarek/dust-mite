Closes #182 in part · two-way door · blast radius: internal RAM · DUT run: done, 1 of 3 criteria met

## Check these against the ticket

Everything else follows #182 as written.

1. **This PR doesn't reach #182's 22 Camera frames per second: it reaches 17.4.** Base64 and cJSON encoding cap the rate until #104 moves Camera frames to MJPEG. On that branch the same changes reach 24.0. Merge this now, or hold it for #104? [results](#dut-run)
2. **Task stats are read every 10 s instead of every 100 ms,** through a new `CONFIG_SYSTEM_METRICS_TASK_STATS_REFRESH_MS`. #182 doesn't mention task stats; the DUT run found Camera frames dropped during each read. Task stats stay off unless `sdkconfig.defaults.all`. [`system_metrics.cpp` L54–58](https://github.com/ltowarek/dust-mite/blob/010a21ff04b24a3be5673f4b1b49c4b6db0a035a/car/components/tracing/system_metrics.cpp#L54-L58)
3. **Eight static Wi-Fi TX buffers and the old RX values.** Moving Wi-Fi to PSRAM makes TX buffers static and raises the RX defaults; these counts keep idle internal RAM where it was. [`sdkconfig.defaults` L27–29](https://github.com/ltowarek/dust-mite/blob/010a21ff04b24a3be5673f4b1b49c4b6db0a035a/car/sdkconfig.defaults#L27-L29)
4. **A third frame buffer (#182's candidate 3) not tried.** Candidates 1 and 2 were enough to measure the effect.

## What isn't tested automatically

- **Frame rate and heap.** Only the DUT run sees Wi-Fi sends and DMA interrupts; no QEMU test does.
- **Builds without `.all` and `.profiling`:** firmware builds in CI, internal RAM not measured.

## Reading route

1. [`sdkconfig.defaults` L20–29](https://github.com/ltowarek/dust-mite/blob/010a21ff04b24a3be5673f4b1b49c4b6db0a035a/car/sdkconfig.defaults#L20-L29): five settings, the whole fix for the send.
2. [`system_metrics.cpp` L54–58](https://github.com/ltowarek/dust-mite/blob/010a21ff04b24a3be5673f4b1b49c4b6db0a035a/car/components/tracing/system_metrics.cpp#L54-L58): the refresh gate.

## DUT run

Car agent session, 2026-10-24: `sdkconfig.defaults` + `.all` + `.profiling`, `observability/tests/e2e/test_camera_stream.py --dut`, two runs on each side.

| | `main` | This PR | #182 asks |
|---|---|---|---|
| Camera frames per second | 14.4 / 12.5 | 17.4 / 17.4 | ≥ 22 ❌ |
| Send p95 | — | — | ≤ 45 ms, needs #104 |
| Internal free heap, minimum while streaming | 104.9 / 97.1 KB | 117.5 / 119.4 KB | no fall ✅ |

<details>
<summary>Shape of the change</summary>

```diff
 stream task, per Camera frame
   take Camera frame
-  send it                     # waits 3–4 rounds of ACKs: 5760 B TCP send buffer, frames up to 26 KB
+  send it                     # queued whole: 32 KB TCP send buffer, segments in PSRAM
 system metrics, per collection
-  uxTaskGetSystemState()      # every 100 ms; masks interrupts, so the camera misses DMA
+  uxTaskGetSystemState()      # every CONFIG_SYSTEM_METRICS_TASK_STATS_REFRESH_MS, default 10 s
```

</details>
