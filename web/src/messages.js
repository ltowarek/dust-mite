export function updateStream(image, data) {
  image.src = `data:image/jpeg;base64,${data}`;
}

export function updateTelemetry(elements, data) {
  elements.timestamp.innerText = data.timestamp;
  elements.rssi.innerText = `${data.rssi} dBm`;
  elements.speed.innerText = `${data.speed.toFixed(2)} km/h`;

  const a = data.accelerometer;
  const m = data.magnetometer;
  const g = data.gyroscope;
  elements.accelerometer.innerText = `${a.x.toFixed(2)}, ${a.y.toFixed(2)}, ${a.z.toFixed(2)} g`;
  elements.magnetometer.innerText = `${m.x.toFixed(2)}, ${m.y.toFixed(2)}, ${m.z.toFixed(2)} G`;
  elements.gyroscope.innerText = `${g.x.toFixed(2)}, ${g.y.toFixed(2)}, ${g.z.toFixed(2)} degrees/s`;
  elements.distance_ahead.innerText = `${data.distance_ahead} cm`;
}

export function handleMessage(messageData, elements) {
  if (messageData.type === "stream") {
    updateStream(elements.image, messageData.data);
  } else if (messageData.type === "telemetry") {
    updateTelemetry(elements, messageData.data);
  }
}
