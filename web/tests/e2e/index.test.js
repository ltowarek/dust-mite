import { expect, test } from "@playwright/test";
import { WebSocketServer } from "ws";

let wss;

test.beforeAll(() => {
  wss = new WebSocketServer({ port: 8765 });
});

test.afterAll(() => {
  wss.close();
});

test("renders stream and telemetry from WebSocket", async ({ page }) => {
  const clientConnected = new Promise((resolve) => {
    wss.on("connection", resolve);
  });

  await page.goto("http://localhost:5173");
  const ws = await clientConnected;

  ws.send(
    JSON.stringify({
      type: "stream",
      data: "dGVzdA==",
    }),
  );

  ws.send(
    JSON.stringify({
      type: "telemetry",
      data: {
        timestamp: "2024-01-01T00:00:00Z",
        rssi: -50,
        speed: 5.25,
        accelerometer: { x: 0.1, y: -0.2, z: 9.8 },
        magnetometer: { x: 100.5, y: 200.3, z: 50.2 },
        gyroscope: { x: 0.5, y: 1.2, z: -0.3 },
        distance_ahead: 150,
      },
    }),
  );

  await expect(page.locator("#speed")).toHaveText("5.25 km/h");
  await expect(page.locator("#distance_ahead")).toHaveText("150 cm");
  await expect(page.locator("#rssi")).toHaveText("-50 dBm");
  await expect(page.locator("#image")).toHaveAttribute("src", "data:image/jpeg;base64,dGVzdA==");
});
