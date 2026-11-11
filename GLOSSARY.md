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

### Apps

**Terminal app**:
The app a person runs in a terminal to reach the car through the streamer.
_Avoid_: Controller, controller CLI, gamepad CLI

**Web app**:
The app a person runs in a browser to reach the car through the streamer.
_Avoid_: Frontend, web client, web controller

### Driver input

**Input device**:
A device a Driver produces Input readings with: the keyboard or a gamepad.
_Avoid_: Input backend, controller (for the device)

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

### Testing

**DUT**:
The real car as the device a test runs against; QEMU emulating the car's ESP32 is not a DUT.

**DUT-gated test**:
A test that needs the DUT, so it is skipped without one and never runs in CI.
_Avoid_: DUT test

**DUT run**:
Checking a change on the DUT: running every DUT-gated test and any check its PR asks for.
_Avoid_: Car check, car test, hardware test, HIL test

### Agent workflow

**AFK agent session**:
An agent session that works tickets on its own, with no one answering its questions. It says nothing about whether anyone is near the car.
_Avoid_: Unattended session, background agent

**AFK loop**:
The system that starts an AFK run on each ticket the maintainer labels for one, one at a time in the order they were labelled, and chains a spec's sub-issues and waiting tickets as their blockers close.
_Avoid_: Agent swarm, runner, Ralph loop, factory, orchestrator

**AFK run**:
One run of the AFK loop: an AFK agent session on one ticket, from its start until it ends, with or without a draft PR.
_Avoid_: Job, workflow run, agent run

**Car agent session**:
An AFK agent session, started at the maintainer's desk with the car connected, that works through every ticket waiting on the car, for its fix or for a DUT run of its PR, while the maintainer stays by it.
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

**Spec gap**:
A question about what a change does (its behaviour, an interface other code uses, its scope or an acceptance criterion) that the ticket's agent brief, its spec and the repo's docs leave open or contradict. How the change does it is the agent's call.
_Avoid_: Blocker, open question, ambiguity
