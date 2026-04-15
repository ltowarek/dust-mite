import { beforeEach, describe, expect, test } from "vitest";
import { updateStream, updateTelemetry } from "../../src/messages.js";

describe("updateStream", () => {
  test("sets image src to base64 JPEG data URI", () => {
    document.body.innerHTML = '<img id="image">';
    const image = document.getElementById("image");

    updateStream(image, "dGVzdA==");

    expect(image.src).toBe("data:image/jpeg;base64,dGVzdA==");
  });
});

describe("updateTelemetry", () => {
  let elements;

  beforeEach(() => {
    document.body.innerHTML = `
      <dd id="timestamp"></dd>
      <dd id="rssi"></dd>
      <dd id="speed"></dd>
      <dd id="accelerometer"></dd>
      <dd id="magnetometer"></dd>
      <dd id="gyroscope"></dd>
      <dd id="distance_ahead"></dd>
    `;
    elements = {
      timestamp: document.getElementById("timestamp"),
      rssi: document.getElementById("rssi"),
      speed: document.getElementById("speed"),
      accelerometer: document.getElementById("accelerometer"),
      magnetometer: document.getElementById("magnetometer"),
      gyroscope: document.getElementById("gyroscope"),
      distance_ahead: document.getElementById("distance_ahead"),
    };
  });

  test("renders all telemetry fields with correct formatting", () => {
    updateTelemetry(elements, {
      timestamp: "2024-01-01T00:00:00Z",
      rssi: -50,
      speed: 5.256,
      accelerometer: { x: 0.1, y: -0.2, z: 9.8 },
      magnetometer: { x: 100.5, y: 200.3, z: 50.2 },
      gyroscope: { x: 0.5, y: 1.2, z: -0.3 },
      distance_ahead: 150,
    });

    expect(elements.timestamp.innerText).toBe("2024-01-01T00:00:00Z");
    expect(elements.rssi.innerText).toBe("-50 dBm");
    expect(elements.speed.innerText).toBe("5.26 km/h");
    expect(elements.accelerometer.innerText).toBe("0.10, -0.20, 9.80 g");
    expect(elements.magnetometer.innerText).toBe("100.50, 200.30, 50.20 G");
    expect(elements.gyroscope.innerText).toBe("0.50, 1.20, -0.30 degrees/s");
    expect(elements.distance_ahead.innerText).toBe("150 cm");
  });
});
