Closes #197 · two-way door · blast radius: streamer · DUT run: not needed

## Check these against the ticket

Everything else follows #197 as written.

1. **A Viewer still starting up when shutdown begins is cancelled after 0.1 s**, as in `aiohttp`'s own graceful-shutdown example. #197 says Viewer responses end, not what happens to one mid-handshake. [`streamer.py` L294](https://github.com/ltowarek/dust-mite/blob/db5ff8436f945e06734a12751079fb93657c2edc/controller/src/controller/streamer.py#L294)
2. **The profiler's stop doesn't wait for an export already in flight.** Both may run; the aggregator's lock gives each sample to one of them. Waiting instead would hold the exit for up to one export's timeout. [`sampler.py` L76–84](https://github.com/ltowarek/dust-mite/blob/db5ff8436f945e06734a12751079fb93657c2edc/controller/src/otlp_profiler/sampler.py#L76-L84)
3. **A new ground rule in `CONTRIBUTING.md`:** a test's expected values come from outside the code under test. #197 doesn't ask for it; the close-code checks needed it. [`CONTRIBUTING.md` L12](https://github.com/ltowarek/dust-mite/blob/db5ff8436f945e06734a12751079fb93657c2edc/CONTRIBUTING.md#L12)

## What isn't tested automatically

- **The signal wiring,** as #197 allows. Checked by hand against the car doubles and a recording OTLP server: for SIGTERM and SIGINT the client got 1001 and the process exited 0 in about 0.17 s.
- **7 lines of `streamer.py`** per Codecov, all in `_serve_until_signalled`.

## Reading route

1. [`streamer.py` L307–328](https://github.com/ltowarek/dust-mite/blob/db5ff8436f945e06734a12751079fb93657c2edc/controller/src/controller/streamer.py#L307-L328): signal handlers and Viewer shutdown.
2. [`test_streamer.py` L622–671](https://github.com/ltowarek/dust-mite/blob/db5ff8436f945e06734a12751079fb93657c2edc/controller/tests/integration/test_streamer.py#L622-L671): what "cleanly" means.
3. [`sampler.py` L76–84](https://github.com/ltowarek/dust-mite/blob/db5ff8436f945e06734a12751079fb93657c2edc/controller/src/otlp_profiler/sampler.py#L76-L84): the last profile export.

<details>
<summary>Shape of the change</summary>

```diff
 main
-  asyncio.run(_serve_until_cancelled)        # SIGINT raised KeyboardInterrupt; SIGTERM killed it
+  asyncio.run(_serve_until_signalled)
+    add_signal_handler(SIGTERM, SIGINT → stop.set)
     serve_streamer
       /drive, /telemetry                      # leaving closes clients with 1001 Going Away
       /camera
+        on_shutdown: Outbox.close() per Viewer
-    await Event().wait()
+    await stop.wait()
+  atexit: Sampler.stop()                      # exports the profile window still open
```

</details>

<details>
<summary>Evidence: before and after</summary>

On `main`, a Viewer reading when the streamer stops fails with `IncompleteRead`, and the profile window still open is dropped. On this branch:

```text
test_stopping_ends_viewer_responses                      PASSED   (fails on main)
test_stopping_closes_websocket_clients_with_going_away   PASSED   [drive, telemetry]
test_stopping_closes_the_connections_to_the_car          PASSED   [camera, telemetry, drive]
test_stop_exports_the_window_still_open                  PASSED
```

</details>
