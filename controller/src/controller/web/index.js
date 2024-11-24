window.addEventListener("DOMContentLoaded", () => {
  const socket = new WebSocket("ws://<ESP32_ADDRESS>/stream");
  socket.binaryType = 'arraybuffer';

  socket.onmessage = (event) => {
    const array_u8 = new Uint8Array(event.data);
    image.src = "data:image/jpeg;base64," + window.btoa(String.fromCharCode.apply(null, array_u8));
  };

  const image = document.getElementById('image');
});
