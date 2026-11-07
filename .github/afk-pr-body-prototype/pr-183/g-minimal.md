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

## Evidence

### DUT run

_Car agent session, 2026-10-24: `sdkconfig.defaults` + `.all` + `.profiling`, two runs on `main` and two on this branch._

| | `main` | This PR | #182 asks |
|---|---|---|---|
| Camera frames per second | 14.4 / 12.5 | 17.4 / 17.4 | at least 22: **not met**, base64 and cJSON cap it until #104 |
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
