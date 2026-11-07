**Changed:** a Camera frame now fits the TCP send buffer whole (32 KB, in PSRAM), and task stats are read every 10 s instead of every 100 ms. Both made sends outlast a frame period. Part of #182.
**Verified:** DUT run, two runs each: 14.4 / 12.5 → 17.4 / 17.4 Camera frames per second; minimum internal free heap 104.9 / 97.1 → 117.5 / 119.4 KB. #182's 22 per second needs #104 as well.
**Could break:** internal RAM in builds without `.all` and `.profiling`, which weren't measured.
**Safe to merge:** yes. Two-way door: revert and flash again.

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

<details>
<summary>Worth understanding: why a bigger TCP send buffer raises the frame rate</summary>

The send call returns only once lwIP has accepted every byte. With 5760 bytes of buffer, a 20 KB Camera frame waits for three or four rounds of ACKs over Wi-Fi. Meanwhile the stream task can't take the next Camera frame, and with two frame buffers the camera has nowhere to put one, so it drops it. With 32 KB the whole Camera frame is copied in and the call returns; the ACKs arrive while the camera fills the next buffer.

</details>
