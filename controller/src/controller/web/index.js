window.addEventListener("DOMContentLoaded", () => {
  const stream_socket = new WebSocket("ws://<ESP32_ADDRESS>/stream");
  stream_socket.binaryType = 'arraybuffer';

  stream_socket.onmessage = (event) => {
    const array_u8 = new Uint8Array(event.data);
    image.src = "data:image/jpeg;base64," + window.btoa(String.fromCharCode.apply(null, array_u8));
  };

  const image = document.getElementById('image');

  const telemetry_socket = new WebSocket("ws://<ESP32_ADDRESS>/telemetry");

  telemetry_socket.onmessage = (event) => {
    console.log(event.data);
    const data = JSON.parse(event.data);
    timestamp.innerText = data.timestamp;
  };

  const timestamp = document.getElementById('timestamp');
});
