window.addEventListener("DOMContentLoaded", () => {
  const socket = new WebSocket("ws://localhost:8765");

  socket.onmessage = (event) => {
    const event_data = JSON.parse(event.data);

    if (event_data["type"] == "stream") {
      data = event_data["data"];
      image.src = "data:image/jpeg;base64," + data;
    } else if (event_data["type"] == "telemetry") {
      data = event_data["data"];

      timestamp.innerText = data.timestamp;
      rssi.innerText = `${data.rssi} dBm`;
      speed.innerText = `${data.speed.toFixed(2)} km/h`;

      const a = data.accelerometer;
      const m = data.magnetometer;
      const g = data.gyroscope;
      accelerometer.innerText = `${a.x.toFixed(2)}, ${a.y.toFixed(2)}, ${a.z.toFixed(2)} g`;
      magnetometer.innerText = `${m.x.toFixed(2)}, ${m.y.toFixed(2)}, ${m.z.toFixed(2)} G`;
      gyroscope.innerText = `${g.x.toFixed(2)}, ${g.y.toFixed(2)}, ${g.z.toFixed(2)} degrees/s`;

      distance_ahead.innerText = `${data.distance_ahead} cm`;
    }
  };

  const image = document.getElementById("image");
  const timestamp = document.getElementById("timestamp");
  const rssi = document.getElementById("rssi");
  const speed = document.getElementById("speed");
  const accelerometer = document.getElementById("accelerometer");
  const magnetometer = document.getElementById("magnetometer");
  const gyroscope = document.getElementById("gyroscope");
  const distance_ahead = document.getElementById("distance_ahead");
});
