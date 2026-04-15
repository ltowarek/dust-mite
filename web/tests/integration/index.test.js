import { beforeEach, describe, expect, test } from "vitest";
import { handleMessage } from "../../src/messages.js";

describe("handleMessage", () => {
  let elements;

  beforeEach(() => {
    document.body.innerHTML = `
      <img id="image">
      <dd id="timestamp"></dd>
      <dd id="rssi"></dd>
      <dd id="speed"></dd>
      <dd id="accelerometer"></dd>
      <dd id="magnetometer"></dd>
      <dd id="gyroscope"></dd>
      <dd id="distance_ahead"></dd>
    `;
    elements = {
      image: document.getElementById("image"),
      timestamp: document.getElementById("timestamp"),
      rssi: document.getElementById("rssi"),
      speed: document.getElementById("speed"),
      accelerometer: document.getElementById("accelerometer"),
      magnetometer: document.getElementById("magnetometer"),
      gyroscope: document.getElementById("gyroscope"),
      distance_ahead: document.getElementById("distance_ahead"),
    };
  });

  test("routes stream message to image element", () => {
    handleMessage({ type: "stream", data: "dGVzdA==" }, elements);

    expect(elements.image.src).toBe("data:image/jpeg;base64,dGVzdA==");
  });

  test("routes telemetry message to telemetry elements", () => {
    handleMessage(
      {
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
      },
      elements,
    );

    expect(elements.speed.innerText).toBe("5.25 km/h");
    expect(elements.distance_ahead.innerText).toBe("150 cm");
  });

  test("ignores unknown message types", () => {
    handleMessage({ type: "unknown", data: {} }, elements);

    expect(elements.image.src).toBe("");
    expect(elements.speed.textContent).toBe("");
  });
});
