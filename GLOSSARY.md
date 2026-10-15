# Dust Mite

A remote-controlled car whose ESP32 firmware exposes endpoints to a host-side streamer, which relays Camera frames, telemetry and Drive commands to its own clients.

## Language

### Car endpoints

**Endpoint**:
One path on the car, served by its own HTTP server instance on its own port.
_Avoid_: Route, channel (for the car side)

**Drive endpoint**:
The WebSocket endpoint (`/`) on which the car receives Drive commands.
_Avoid_: Control endpoint, controller endpoint, root endpoint

**Camera endpoint**:
The HTTP endpoint (`/stream`) on which the car streams Camera frames.
_Avoid_: Stream endpoint, video endpoint

**Telemetry endpoint**:
The WebSocket endpoint (`/telemetry`) on which the car sends Telemetry messages.

**Push endpoint**:
The Camera or Telemetry endpoint: the car sends and the client only reads.

### WebSocket messages

**WebSocket message**:
The application-level unit of one WebSocket connection, sent and received whole: a Drive command, a Telemetry message or a Collision-monitor message.
_Avoid_: Message (on its own), packet, payload

**WebSocket frame**:
The wire unit a WebSocket message travels in; one WebSocket message is one or more WebSocket frames.
_Avoid_: Frame (on its own)

**Drive command**:
The WebSocket message a client sends to steer the car.
_Avoid_: Control message, drive packet

**Telemetry message**:
The WebSocket message that carries one set of sensor readings.

**Collision-monitor message**:
The WebSocket message that tells a client whether the collision monitor is blocking forward motion.

### Camera

**Camera frame**:
One picture captured by the camera, whether or not the streamer has drawn on it.
_Avoid_: Frame (on its own), image, picture, snapshot, video frame
