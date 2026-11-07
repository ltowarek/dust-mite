**Changed:** SIGTERM and SIGINT stop the streamer by ending its entry point: WebSocket clients get 1001, Viewer responses end, the connections to the car close, and the profiler exports its last window. Closes #197.
**Verified:** 7 new tests (10 cases) through the entry point and in units; the Viewer one fails on `main`. The signal wiring by hand: exit 0 in about 0.17 s.
**Could break:** a stop that hangs now waits 10 s for `docker stop`'s SIGKILL.
**Safe to merge:** yes. Two-way door: a revert restores the old behaviour, nothing persists.

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
<summary>Worth understanding: why one word in <code>run_streamer.sh</code> decides whether SIGTERM arrives</summary>

`docker stop` signals PID 1 of the container. Without `exec`, PID 1 is the shell running the script, and the shell doesn't pass SIGTERM on to its child, so Docker sends SIGKILL after 10 s. `exec` replaces the shell with the streamer, which then is PID 1 and gets the signal itself.

</details>
