import http from "node:http";
import { expect, test } from "@playwright/test";
import { WebSocketServer } from "ws";
import { Command } from "../../src/command.js";

// An 8x8 grey JPEG.
const JPEG = Buffer.from(
  "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAIBAQEBAQIBAQECAgICAgQDAgICAgUEBAMEBgUGBgYFBgYGBwkIBgcJBwYGCAsICQoKCgoKBggLDAsKDAkKCgr/2wBDAQICAgICAgUDAwUKBwYHCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgr/wAARCAAIAAgDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwAooooA/9k=",
  "base64",
);

let streamerSpy;
let cameraStub;

function sendPart(response) {
  const head = `\r\n--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ${JPEG.length}\r\n\r\n`;
  response.write(Buffer.concat([Buffer.from(head), JPEG]));
}

test.beforeAll(() => {
  streamerSpy = new WebSocketServer({ port: 8765 });
  cameraStub = http
    .createServer((request, response) => {
      response.writeHead(200, { "Content-Type": "multipart/x-mixed-replace;boundary=frame" });
      sendPart(response);
      const timer = setInterval(() => sendPart(response), 50);
      request.on("close", () => clearInterval(timer));
    })
    .listen(8766);
});

test.afterAll(() => {
  streamerSpy.close();
  cameraStub.closeAllConnections();
  cameraStub.close();
});

function connectionTo(path) {
  return new Promise((resolve) => {
    streamerSpy.on("connection", (ws, request) => {
      if (request.url === path) {
        resolve(ws);
      }
    });
  });
}

test("renders the camera stream from the streamer", async ({ page }) => {
  await page.goto("http://localhost:5173");

  await expect.poll(() => page.locator("#image").evaluate((img) => img.naturalWidth)).toBe(8);
});

test("renders the telemetry feed from its own socket", async ({ page }) => {
  const telemetry = connectionTo("/telemetry");

  await page.goto("http://localhost:5173");

  (await telemetry).send(
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
});

async function openDriveSocket(page) {
  const drive = connectionTo("/drive");
  await page.goto("http://localhost:5173");

  const received = [];
  (await drive).on("message", (data) => received.push(JSON.parse(data.toString())));
  await page.locator("body").focus();
  return received;
}

test("holding W advances, releasing brakes", async ({ page }) => {
  const received = await openDriveSocket(page);

  await page.keyboard.down("KeyW");
  await expect.poll(() => received.at(-1)).toEqual({ command: Command.ADVANCE, value: 50 });

  await page.keyboard.up("KeyW");
  await expect.poll(() => received.at(-1)).toEqual({ command: Command.BRAKE, value: null });
});

test("moving focus away from the page while a key is held stops the car", async ({ page }) => {
  const received = await openDriveSocket(page);

  await page.keyboard.down("KeyD");
  await expect.poll(() => received.at(-1)).toEqual({ command: Command.TURN_RIGHT, value: 50 });

  await page.evaluate(() => window.dispatchEvent(new Event("blur")));
  await expect.poll(() => received.at(-1)).toEqual({ command: Command.BRAKE, value: null });
});

test("shows why the page cannot drive when the streamer refuses it", async ({ page }) => {
  const drive = connectionTo("/drive");
  await page.goto("http://localhost:5173");

  (await drive).close(1013, "another driver is connected");

  await expect(page.locator("#drive_status")).toHaveText(
    "Not driving: another driver is connected",
  );
});
