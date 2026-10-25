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

**Car feed**:
The streamer's one shared connection to a Push endpoint, open only while a client is subscribed; every client reads the same Car feed.
_Avoid_: Subscription, channel

### WebSocket messages

**WebSocket message**:
The application-level unit of one WebSocket connection, sent and received whole: a Drive command, a Telemetry message or a Collision-monitor message.
_Avoid_: Message (on its own), packet, payload

**WebSocket frame**:
The wire unit a WebSocket message travels in; one WebSocket message is one or more WebSocket frames.
_Avoid_: Frame (on its own)

**Drive command**:
The WebSocket message a Driver sends to control the car: a Velocity command, a brake, or a camera pan or tilt.
_Avoid_: Control message, operator command, teleop command, drive packet

**Velocity command**:
A Drive command that sets the car's speed or turning: advance, retreat, turn left or turn right.
_Avoid_: Motion command, movement command

**Driver**:
The one client allowed to send Drive commands at a time.
_Avoid_: Operator, pilot

**Telemetry message**:
The WebSocket message that carries one Telemetry reading.

**Telemetry reading**:
One timestamped set of the car's sensor readings.
_Avoid_: Telemetry packet, telemetry sample

**Collision-monitor message**:
The WebSocket message that tells a client whether the collision monitor is blocking forward motion.

### Camera

**Camera frame**:
One picture captured by the camera, whether or not the streamer has drawn on it.
_Avoid_: Frame (on its own), image, picture, snapshot, video frame

**Camera stream**:
The never-ending response that carries Camera frames, one Camera stream part each. The car serves it on the Camera endpoint, and the streamer serves a processed copy.
_Avoid_: Video stream, feed

**Camera stream part**:
One Camera frame in the Camera stream, together with its headers, including the Camera frame's trace context.
_Avoid_: Chunk, frame (on its own)

**Viewer**:
A client watching the streamer's Camera stream. Any number can watch at once.
_Avoid_: Watcher, subscriber
