# One HTTP server instance per car endpoint, each accepting one client

An `esp_http_server` instance does all of its work on one task. When the Drive, Camera and Telemetry endpoints shared one instance, a camera or telemetry send blocked on a client's TCP window also stopped drive commands from being read ([#150](https://github.com/ltowarek/dust-mite/pull/150)). Bounding sends to one per endpoint ([#156](https://github.com/ltowarek/dust-mite/pull/156)) shortened that delay but did not remove it. Each endpoint therefore runs on its own instance and its own port (Drive 80, Camera 81, Telemetry 82), so a slow or stalled reader on one endpoint cannot delay another ([#154](https://github.com/ltowarek/dust-mite/issues/154)).

Each endpoint accepts one client and refuses a second with HTTP 503 before the WebSocket upgrade. The streamer is the only client of the car and fans out to its own clients, so one session per endpoint is enough. This keeps every instance at two sessions (the owner and one connection being refused), which keeps the lwIP socket budget small.

## Considered Options

- **One shared instance with bounded sends ([#156](https://github.com/ltowarek/dust-mite/pull/156)).** Rejected: a client that stops reading still holds the shared task for each send's timeout, about 6 s, and drive commands wait behind it.
- **Async request handlers with a worker pool (`httpd_req_async_handler_begin`).** The idiomatic ESP-IDF way to keep long HTTP requests off the server task. Rejected: httpd stops polling a socket while a worker owns it, so the client's WebSocket CLOSE frame is never read ([#112](https://github.com/ltowarek/dust-mite/issues/112)). The car used this design before [#124](https://github.com/ltowarek/dust-mite/pull/124) replaced it with `httpd_queue_work`.
- **A separate instance for the Camera endpoint only.** Rejected: a stalled Telemetry client delays drive commands in the same way.
- **Video over UDP or WebRTC ([#152](https://github.com/ltowarek/dust-mite/issues/152)).** Deferred: a larger change that does not by itself separate telemetry from drive commands.

## Consequences

- Clients address each endpoint by port as well as path; a wrong port returns 404.
- A client that disappears without closing its connection keeps its endpoint until the car detects the dead session, so reconnects receive 503 in the meantime.
