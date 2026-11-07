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
  **After:** by hand, `streamer` against the car doubles and a recording OTLP server, for both SIGTERM and SIGINT: the client got 1001, the process exited 0 in about 0.17 s, and logs, metrics and traces were posted after the signal.
- **DUT run:** not needed. The car doubles cover every connection the change closes, and the car firmware is unchanged.

## Merge Danger

**Door:** two-way

**Blast Radius:** streamer

A stop that hangs now waits for `docker stop`'s SIGKILL after 10 s instead of dying at once.

---

🤖 Written by an [AFK run](https://github.com/ltowarek/dust-mite/actions) (example link).
