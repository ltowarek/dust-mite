# MJPEG over HTTP for Camera frames, with trace context in each part's headers

Camera frames travelled as JSON over WebSocket, with the JPEG base64-encoded. On the car, the constant-time mbedtls base64 encoder and two cJSON copies dominated the CPU profile of every send ([#104](https://github.com/ltowarek/dust-mite/issues/104)), and base64 added about a third to every Camera frame on both hops (car to streamer, streamer to browser). Both hops therefore carry Camera frames as MJPEG over HTTP (`multipart/x-mixed-replace`): one long-lived response per client, one part per Camera frame, the JPEG bytes unencoded. It is the format most ESP32 camera projects use, including Espressif's own `CameraWebServer` example. The car sends each part straight from the camera frame buffer with no copy, and neither side gains a dependency. Each part carries `traceparent` (and `tracestate` when present) as a part header, in the way Espressif's example carries `X-Timestamp`, so the streamer continues the car's trace for every Camera frame.

The browser shows the stream in an `<img>`, which cannot read part headers, so the browser no longer continues car or streamer traces: it emits only its own signals, and traces that involve the browser start there ([#170](https://github.com/ltowarek/dust-mite/issues/170)). Browser frame-rate measurement goes with it; the streamer counts the Camera frames it sends to each viewer instead. Drive commands, Telemetry messages and Collision-monitor messages stay JSON over WebSocket, `traceparent` included.

## Considered Options

- **Faster base64 and a hand-built JSON envelope.** Rejected: no protocol change, but still encodes every Camera frame and keeps base64's size overhead.
- **CBOR over WebSocket.** An IETF standard with maintained libraries on all three sides, and it keeps per-frame trace context in the browser. Rejected: unusual among ESP32 camera projects, and it adds a dependency on every side for what MJPEG does without one.
- **A binary WebSocket message preceded by a JSON text message for the metadata.** Rejected: two sends per Camera frame, and a receiver must pair them; a lost or reordered message attaches the wrong trace context.
- **WebRTC.** Rejected: browsers expect H.264/VP8-class video tracks, which means a software encode on the car and a decode and re-encode in the streamer, plus signalling; media tracks have no standard place for per-frame trace context.
- **Protobuf (nanopb).** Rejected: the car is moving away from its protobuf and Abseil dependencies.
- **Foxglove WebSocket protocol.** Rejected: deprecated and unmaintained.

## Consequences

- The Camera endpoint is an HTTP endpoint, not a WebSocket one; it amends [ADR 0001](0001-one-http-server-per-car-endpoint.md) for that endpoint only.
- The car's `/stream` handler hands the request to the stream task with `httpd_req_async_handler_begin`, so the Camera instance's own task stays free to refuse a second client with HTTP 503. ADR 0001 rejected async handlers because httpd does not read a WebSocket CLOSE frame from a socket a worker owns; plain HTTP has no CLOSE frame, and the stream task detects a departed client when a send fails.
- The streamer reads the car's stream with `requests`, which it already depends on, parsing each part's headers with `http.client.parse_headers` and reading the JPEG by its `Content-Length`. It serves its viewers from a `ThreadingHTTPServer` on its own port, beside the WebSocket server. [ADR 0003](0003-one-event-loop-with-websockets-and-aiohttp.md) replaces both with `aiohttp` on the streamer's event loop.
