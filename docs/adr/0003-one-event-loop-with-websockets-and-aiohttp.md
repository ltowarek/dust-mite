# One event loop in the streamer, with `websockets` for WebSocket and `aiohttp` for HTTP

The streamer was built from threads: one per WebSocket client, one per Viewer, one per Car feed and one inside each client of a car Endpoint. Most waits woke every 0.2 s to recheck whether they should stop, a Viewer's departure was noticed by peeking at its socket, and a Driver's Drive commands blocked their handler while the car's Drive endpoint was unreachable ([#5](https://github.com/ltowarek/dust-mite/issues/5)). The streamer therefore runs on one asyncio event loop: waiting becomes awaiting, and stopping becomes cancellation.

Two libraries share the loop. `websockets` carries every WebSocket connection: it already serves the `/drive` and `/telemetry` Streamer endpoints and connects to the car's Drive and Telemetry endpoints. `aiohttp` carries the Camera stream on both hops, because `websockets` serves only WebSocket handshakes and cannot serve a never-ending HTTP response. A client session connects to the car's Camera endpoint, and a streaming response serves the processed Camera stream to each Viewer.

The streamer parses the car's Camera stream part by part from the response's content stream: the headers up to the blank line, through `http.client.parse_headers`, then exactly `Content-Length` bytes of JPEG. It does not use `aiohttp`'s `MultipartReader`. After a part's `Content-Length` bytes, that reader waits for a CRLF, which the car writes only before the next boundary. Each part would therefore be held back by one Camera frame, and the last Camera frame of a stalled car would never reach Viewers.

Every connection that stays open, on either library, reconnects after a fixed 1 s. Each attempt opens the connection with `async with`, so cancellation closes it at once. The `websockets` reconnect loop (`async for ... in connect(...)`) is not used. Its delay starts at a random 0 to 5 s and grows to 90 s. The delay resets after any successful open, so a peer that accepts and then closes is reconnected immediately. A connection that it yields stays open after the loop body is cancelled, until the generator is closed by hand.

## Considered Options

- **Staying threaded.** Rejected: it keeps a thread per connection, the polling loops and the socket peeking described above.
- **Hand-written asyncio streams.** Rejected: the streamer would implement HTTP itself, including request parsing, chunked transfer decoding of the car's response and the response framing for Viewers.
- **`aiohttp` for everything.** Rejected: the WebSocket side already runs on `websockets`, including the close handling and the reconnect policy, and moving it would rewrite that side with no gain.

## Consequences

- Camera frame processing runs in a worker thread through `asyncio.to_thread`, so it never blocks the event loop. The whole per-part relay runs in the worker, so its spans start there and the profiler links the worker's samples to them.
- `aiohttp` sends the Camera stream to HTTP/1.1 Viewers with chunked transfer encoding. The Camera stream parts inside the response are unchanged.
- `requests` remains a dependency of the profiler's exporter only.
