Closes #197.

## Summary

`docker stop` (SIGTERM) and Ctrl-C (SIGINT) now leave the streamer the way the tests already do: by ending its entry point.

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

## Read first

1. [`streamer.py` L307–328](https://github.com/ltowarek/dust-mite/blob/db5ff8436f945e06734a12751079fb93657c2edc/controller/src/controller/streamer.py#L307-L328): the signal handlers and the Viewer shutdown, the whole change in behaviour.
2. [`test_streamer.py` L622–671](https://github.com/ltowarek/dust-mite/blob/db5ff8436f945e06734a12751079fb93657c2edc/controller/tests/integration/test_streamer.py#L622-L671): the three new tests say what "cleanly" means.
3. [`sampler.py` L76–84](https://github.com/ltowarek/dust-mite/blob/db5ff8436f945e06734a12751079fb93657c2edc/controller/src/otlp_profiler/sampler.py#L76-L84): `stop()` exports once more.

Skim the rest: `outbox.py` only extracts `close()`; the docs add one line each.

## Worth understanding

**Why one word in `run_streamer.sh` decides whether SIGTERM arrives.** `docker stop` signals PID 1 of the container. Without `exec`, PID 1 is the shell running the script, and the shell doesn't pass SIGTERM on to its child, so Docker sends SIGKILL after 10 s. `exec` replaces the shell with the streamer, which then is PID 1 and gets the signal itself.

**Why `loop.add_signal_handler`, not `signal.signal`.** asyncio runs the handler as a normal callback inside the event loop, so `stop.set()` is safe there. A `signal.signal` handler interrupts whatever Python code is running, which may be halfway through the event loop's own bookkeeping.

## Evidence

- **Before:** on `main`, a Viewer reading when the streamer stops fails with `IncompleteRead`, and the profile window still open is dropped.
  **After:**

  ```text
  test_stopping_ends_viewer_responses                      PASSED   (fails on main)
  test_stopping_closes_websocket_clients_with_going_away   PASSED   [drive, telemetry]
  test_stopping_closes_the_connections_to_the_car          PASSED   [camera, telemetry, drive]
  test_stop_exports_the_window_still_open                  PASSED
  ```

- **Before:** no automated test covers the signal wiring.
  **After:** by hand, against the car doubles and a recording OTLP server, for both SIGTERM and SIGINT: the client got 1001, the process exited 0 in about 0.17 s, and logs, metrics and traces were posted after the signal.
- **DUT run:** not needed. The car doubles cover every connection the change closes, and the car firmware is unchanged.

## Merge Danger

**Door:** two-way

Touches none of the repo's one-way doors: partition table, NVS layout, WebSocket message schema, CI workflows.

**Undo:** revert the PR; nothing persists.

**Blast Radius:** streamer

A stop that hangs now waits for `docker stop`'s SIGKILL after 10 s instead of dying at once.
