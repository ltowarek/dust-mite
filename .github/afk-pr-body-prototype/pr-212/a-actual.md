Closes #197. Part of #5.

`docker stop` (SIGTERM) and Ctrl-C (SIGINT) now stop the streamer through the same path the tests use to leave the entry point, instead of killing it mid-flight.

## Commits

1. **Export the profiler's open window when the process exits.** `Sampler.stop()` waits for sampling and any export in flight to end, then exports the window still open; before, those samples were dropped. `otlp_profiler.configure()` registers `stop()` with `atexit`, as the OpenTelemetry SDK providers register their shutdown.
2. **Shut the streamer down cleanly on SIGTERM and SIGINT.**
   - `main`'s event loop handles both signals by setting a stop event, which leaves `serve_streamer`. A repeated signal while stopping does nothing; once the loop has closed, the default handlers are back.
   - The WebSocket server closes its clients with 1001 Going Away and the connections to the car close. Both already followed from leaving the entry point; they are now tested.
   - Viewer responses end with the chunked terminator instead of being cut off. As `aiohttp`'s graceful-shutdown docs do for long-lived connections, the Camera server keeps each open Viewer's Outbox in the app (an `AppKey` holding a `WeakSet`) and closes them in `on_shutdown`, so each handler returns. A Viewer still starting up when shutdown begins is cancelled after 0.1 s, as in `aiohttp`'s own example.
   - `run_streamer.sh` execs the streamer, so `docker stop`'s SIGTERM reaches it rather than the shell running as PID 1.
   - The Copper variant doc and the profiling guide describe the shutdown and the final profile export.
3. **Name close codes in tests with websockets' `CloseCode`.** CONTRIBUTING.md's ground rules now say that a test's expected values come from outside the code under test: a literal, or a named constant from a library or a standard. The 1013 and 1001 checks through the Streamer endpoints use `CloseCode` members.

The decision on repeated signals is written into #197 and the #5 spec.

## Tests

- Integration, through the entry point with real car doubles:
  - Stopping closes `/drive` and `/telemetry` clients with 1001.
  - Stopping ends a Viewer's response; it fails with `IncompleteRead` on `main`.
  - Stopping closes the connections to the car's Camera, Telemetry and Drive endpoints.
- Unit:
  - Closing an Outbox ends its iteration after the messages it holds.
  - `Sampler.stop()` exports the window still open.
- The signal wiring stays a thin layer and has no automated test. It was checked by hand by running the `streamer` process against the car doubles and a recording OTLP server. For both SIGTERM and SIGINT, the client got 1001, the process exited with 0 in about 0.17 s, and logs, metrics and traces were posted after the signal. A profile was posted only when the last window held on-CPU samples, because empty exports are skipped.

🤖 Generated with [Claude Code](https://claude.com/claude-code)




