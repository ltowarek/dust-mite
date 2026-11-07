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

- **Before:** `main`, two runs: 14.4 / 12.5 Camera frames per second; internal free heap at least 104.9 / 97.1 KB while streaming.
  **After:** 17.4 / 17.4 Camera frames per second; internal free heap at least 117.5 / 119.4 KB.

## Merge Danger

**Door:** two-way

**Blast Radius:** internal RAM

The Wi-Fi TX buffers become static. Eight of them and the old RX values keep idle internal RAM where it was in the measured build; builds without `.all` and `.profiling` weren't measured.
