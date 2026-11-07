# Dust Mite

A remote-controlled car whose ESP32 firmware exposes endpoints to a host-side streamer, which relays Camera frames, telemetry and Drive commands to its own clients. The Agent workflow terms cover the agents that maintain it.

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
The streamer's one shared connection to a Push endpoint; every client reads the same Car feed.
_Avoid_: Subscription, channel

### Streamer endpoints

**Streamer endpoint**:
One path on which the streamer serves its clients: `/drive`, `/telemetry` or `/camera`.
_Avoid_: Endpoint (on its own), route, channel

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

### Driver input

**Input reading**:
The Drive command the Driver's input asks for at one moment; a brake when no control is held.
_Avoid_: Reading (on its own), sample, poll result

**Autorepeat**:
The timing of the Driver's Drive commands: a held control's Drive command at once and then repeatedly while it is held, a brake once when every control is released, and nothing while Parked.
_Avoid_: Auto-repeat, send policy, resend loop

**Parked**:
The Driver's state while no control is held, so it sends no Drive commands.

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

### Agent workflow

**AFK agent session**:
An agent session that works tickets on its own, with no one answering its questions. It says nothing about whether anyone is near the car.
_Avoid_: Unattended session, background agent

**AFK loop**:
The system that repeatedly picks a ticket ready for an agent and starts an AFK run on it.
_Avoid_: Agent swarm, runner, Ralph loop, factory, orchestrator

**AFK run**:
One run of the AFK loop: an AFK agent session on one ticket, from the loop picking it until it ends, with or without a draft PR.
_Avoid_: Job, workflow run, agent run

**Car agent session**:
An AFK agent session, started at the maintainer's desk with the car connected, that works through every ticket waiting on the car while the maintainer stays by it.
_Avoid_: Car session, hardware session, bench session

**Interactive agent session**:
An agent session in which the maintainer and the agent take turns: the agent asks and the maintainer answers.
_Avoid_: HITL session

**Ticket**:
One GitHub issue, whatever it asks for.
_Avoid_: Issue (except in GitHub's own feature names), task, story

**Follow-up ticket**:
A ticket an agent files on its own, without the maintainer reviewing its text, for a problem outside the ticket it is working.
_Avoid_: Spin-off, side issue, pre-existing finding

**Agent brief**:
The triage comment that is the contract an agent works from; the rest of the ticket is context.
_Avoid_: Prompt, task description
