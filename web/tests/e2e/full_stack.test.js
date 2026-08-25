import { expect, test } from "@playwright/test";

// In the headless stack, the js service sets VITE_WS_URL=ws://python:8765.
// Traces go to otel-collector:4318 via VITE_OTLP_ENDPOINT.
// Metrics go from the browser to the Vite dev server's /otlp path (VITE_OTLP_METRICS_ENDPOINT),
// which proxies straight to Mimir — Mimir has no CORS support, so this keeps the browser's
// request same-origin instead of routing through the OTel Collector.

const wsUrl = process.env.VITE_WS_URL;

// Verifies the browser can reach the Python streamer over the Docker network.
// The WebSocket should open without error (readyState OPEN).
// Requires the headless stack to be running.
test("connects to Python streamer", async ({ page }) => {
  await page.goto("/");

  const readyState = await page.evaluate(
    (url) =>
      new Promise((resolve) => {
        const ws = new WebSocket(url);
        ws.addEventListener("open", () => resolve(ws.readyState));
        ws.addEventListener("error", () => resolve(ws.readyState));
        setTimeout(() => resolve(ws.readyState), 5000);
      }),
    wsUrl,
  );

  expect(readyState).toBe(1); // WebSocket.OPEN
});

// Requires the car to be connected and the camera to be active.
test("receives live stream", async ({ page }) => {
  await page.goto("/");

  await expect(page.locator("#image")).toHaveAttribute("src", /^data:image\/jpeg;base64,/, {
    timeout: 10000,
  });
});

// Requires the car to be connected and sending telemetry.
test("receives live telemetry", async ({ page }) => {
  await page.goto("/");

  await expect(page.locator("#rssi")).not.toHaveText("", { timeout: 10000 });
});

// Requires the car to be connected and the camera to be active.
// Verifies that the browser exports dust_mite_frames_displayed to Mimir via the Vite dev server's /otlp proxy.
test("exports frames_displayed metric", async ({ page, request }) => {
  await page.goto("/");

  // Wait for at least one frame so the counter has incremented.
  await expect(page.locator("#image")).toHaveAttribute("src", /^data:image\/jpeg;base64,/, {
    timeout: 10000,
  });

  // Allow time for the 500 ms OTLP export cycle to reach Mimir.
  await page.waitForTimeout(2000);

  // Mimir's OTLP receiver maps the OTel resource attribute service.name to
  // the Prometheus "job" label, not a literal "service_name" label.
  const response = await request.get("http://mimir:8080/prometheus/api/v1/query", {
    params: { query: 'dust_mite_frames_displayed{job="dust-mite-web"}' },
  });
  const data = await response.json();
  expect(data.data.result.length).toBeGreaterThan(0);
  expect(Number(data.data.result[0].value[1])).toBeGreaterThan(0);
});
