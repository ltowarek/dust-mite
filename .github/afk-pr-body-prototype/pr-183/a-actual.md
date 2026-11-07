## Stream Camera frames closer to the camera's rate

Closes #182. On `main`, base64 and cJSON encoding of each Camera frame keep the car well below the camera's 25 frames per second (#104). This PR removes two further losses that also apply to the MJPEG stream:

- **TCP send buffer.** lwIP's default send buffer, 5760 bytes or four segments, made each Camera frame's message, up to about 26 KB of base64 JSON, wait three or four rounds of ACKs. The stream task waits for each send before it takes the next frame. The send buffer is now 32 KB, so a message is queued whole. Wi-Fi and lwIP allocate from PSRAM first, so the queued segments stay out of internal RAM. That makes the Wi-Fi TX buffers static and raises the defaults of the static RX buffers and the RX block-ack window. Eight TX buffers and the old RX values keep idle internal RAM where it was.
- **Task stats.** On dual-core ESP-IDF, `uxTaskGetSystemState()` holds the kernel lock, with interrupts masked, while it scans every task's stack. The camera misses DMA interrupts during the scan and drops the frame. The new `CONFIG_SYSTEM_METRICS_TASK_STATS_REFRESH_MS` (default 10000) sets how often the stats are read again; collections in between report the last read. Task stats remain off by default and on only in `sdkconfig.defaults.all`.

## Results

Car with `sdkconfig.defaults` + `.all` + `.profiling`. A WebSocket client reads the Camera endpoint for 60 s after a 30 s settle. Internal free heap comes from `dust_mite_internal_free_heap_bytes`.

| | `main` (2 runs) | This PR (2 runs) |
|---|---|---|
| Camera frames per second | 14.4 / 12.5 | 17.4 / 17.4 |
| Gap between frames, p50 | 64 / 85 ms | 51 / 52 ms |
| Gap between frames, p95 | 123 / 136 ms | 119 / 120 ms |
| Internal free heap, idle | 121.4 / 121.8 KB | 123.3 / 123.3 KB |
| Internal free heap, minimum while streaming | 104.9 / 97.1 KB | 117.5 / 119.4 KB |

#104 removes the encoding by moving to MJPEG over HTTP (ADR 0002). On that branch, the same two changes take the stream from 19.5–20.0 to 24.0 frames per second and the send p95 from 41–44 ms to 19–20 ms.

The issue's acceptance tests (`test_viewer_receives_camera_rate`, `test_car_sends_frames_promptly`) and the Unity benchmark `stream_keeps_the_camera_rate` depend on the MJPEG stream. They stay on `mjpeg-camera-frames` and land with #104.

## Test plan

- [x] Car firmware builds with `sdkconfig.defaults` + `.all` + `.profiling`
- [x] Frame rate and internal heap measured on the car, `main` against this PR (table above)
- [ ] CI

🤖 Generated with [Claude Code](https://claude.com/claude-code)

