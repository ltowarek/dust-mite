import { expect, test } from "@playwright/test";

// In the headless stack, the js service sets VITE_WS_URL=ws://python:8765 and
// VITE_CAMERA_URL=http://python:8766/camera.
// Traces and logs go to otel-collector:4318 via VITE_OTLP_ENDPOINT.

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
    `${wsUrl}/telemetry`,
  );

  expect(readyState).toBe(1); // WebSocket.OPEN
});

// Requires the car to be connected and the camera to be active.
test("receives live stream", async ({ page }) => {
  await page.goto("/");

  await expect
    .poll(() => page.locator("#image").evaluate((img) => img.naturalWidth), { timeout: 10000 })
    .toBeGreaterThan(0);
});

// Requires the car to be connected and sending telemetry.
test("receives live telemetry", async ({ page }) => {
  await page.goto("/");

  await expect(page.locator("#rssi")).not.toHaveText("", { timeout: 10000 });
});

// Requires the car to be connected and sending telemetry, with its motors powered.
test("driving from the keyboard reaches the car", async ({ page }) => {
  await page.goto("/");

  await expect(page.locator("#rssi")).not.toHaveText("", { timeout: 10000 });

  await page.locator("body").focus();
  await page.keyboard.down("KeyW");

  await expect(async () => {
    const speed = Number.parseFloat(await page.locator("#speed").innerText());
    expect(speed).toBeGreaterThan(0);
  }).toPass({ timeout: 10000 });

  await page.keyboard.up("KeyW");

  await expect(async () => {
    const speed = Number.parseFloat(await page.locator("#speed").innerText());
    expect(speed).toBeLessThan(1.0);
  }).toPass({ timeout: 5000 });
});

// Verifies that the browser's uncaught-error logging reaches Loki via the OTel Collector.
// Deliberately triggers a real uncaught error (outside Playwright's own evaluate() try/catch,
// via setTimeout) so the page's own `window.addEventListener("error", ...)` handler fires,
// exactly as it would for a genuine bug.
test("logs an uncaught error to Loki", async ({ page, request }) => {
  await page.goto("/");

  const marker = `e2e uncaught error marker ${Date.now()}`;
  await page.evaluate((message) => {
    setTimeout(() => {
      throw new Error(message);
    }, 0);
  }, marker);

  // Allow time for the BatchLogRecordProcessor's 5 s export cycle to reach the collector.
  await page.waitForTimeout(7000);

  const response = await request.get("http://loki:3100/loki/api/v1/query_range", {
    params: {
      query: `{service_name="dust-mite-web"} |= \`${marker}\``,
    },
  });
  const data = await response.json();
  expect(data.data.result.length).toBeGreaterThan(0);
});
