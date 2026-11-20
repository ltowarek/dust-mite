# The streamer always profiles, the car only in its debug build

The streamer and the car both export CPU profiles to Pyroscope, but they turn profiling on by different rules.

The streamer profiles whenever its profiles endpoint resolves, from `OTEL_EXPORTER_OTLP_PROFILES_ENDPOINT` or from the shared base `OTEL_EXPORTER_OTLP_ENDPOINT`. Its traces and logs follow the same rule, and every other signal on both sides is on whenever its endpoint is set. The headless stack sets the endpoints, so the streamer always profiles in the headless stack. The streamer previously also required an opt-in profiling flag. That flag reached the streamer only through `.env`, so every DUT run that included the profile tests had to regenerate `.env` and left it changed ([#176](https://github.com/ltowarek/dust-mite/issues/176)).

The car profiles only in its debug build, which [car/sdkconfig.defaults.debug](../../car/sdkconfig.defaults.debug) enables. Profiling on the car is a build-time Kconfig option, not a runtime setting. It runs a sampler on the ESP32-S3 and reserves a FreeRTOS thread-local storage slot for span links, so the production build leaves it off, as it does the other debugging tools ([CONTRIBUTING.md](../../CONTRIBUTING.md#profiling-firmware-cpu)).

## Considered Options

- **Keep the opt-in profiling flag for the streamer.** Rejected: it was the only signal on either side behind an opt-in flag, and every DUT run had to rewrite `.env` to turn it on.
- **Turn on profiling in the car's production build.** Rejected: it would spend the car's CPU time and memory on every drive, and the debug build already serves the DUT runs that read car profiles.

## Consequences

- The headless stack's streamer exports profiles to Pyroscope with no switch, and the streamer profile tests need only the stack.
- A streamer started without a profiles endpoint or a base endpoint does not profile.
- Car profiles exist only while the debug build is flashed.
