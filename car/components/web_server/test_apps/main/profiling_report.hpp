#pragma once

// Starts the profiler with an exporter that reports, per export, how far internal RAM fell, so
// pytest_web_server_profiling.py can check on the car that profiling leaves the server the memory
// it runs on. Call before web_server_setup: the profiler swaps the context storage spans are
// activated in.
void profiling_report_setup();
