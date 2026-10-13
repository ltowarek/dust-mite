# Dust Mite

A remote-controlled car whose ESP32 firmware exposes WebSocket endpoints to a host-side streamer, which relays camera, telemetry and drive commands to its own clients.

## Language

### Car endpoints

**Endpoint**:
One WebSocket path on the car, served by its own HTTP server instance on its own port.
_Avoid_: Route, channel (for the car side)

**Drive endpoint**:
The endpoint (`/`) on which the car receives drive commands.
_Avoid_: Control endpoint, controller endpoint, root endpoint

**Camera endpoint**:
The endpoint (`/stream`) on which the car sends camera frames.
_Avoid_: Stream endpoint, video endpoint

**Telemetry endpoint**:
The endpoint (`/telemetry`) on which the car sends sensor readings.

**Push endpoint**:
The Camera or Telemetry endpoint: the car sends and the client only reads.
