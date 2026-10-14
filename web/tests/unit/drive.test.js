import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { Command } from "../../src/command.js";
import { DriveController, driveStatusText } from "../../src/drive.js";

class SocketSpy {
  constructor() {
    this.readyState = WebSocket.OPEN;
    this.sent = [];
  }

  send(payload) {
    this.sent.push(JSON.parse(payload));
  }
}

describe("DriveController", () => {
  let socket;
  let controller;

  beforeEach(() => {
    vi.useFakeTimers();
    socket = new SocketSpy();
    controller = new DriveController(socket, window, { getGamepads: () => [] });
    controller.start();
  });

  afterEach(() => {
    controller.stop();
    vi.useRealTimers();
  });

  test("pressing a bound key sends its command immediately", () => {
    window.dispatchEvent(new KeyboardEvent("keydown", { code: "KeyW" }));

    expect(socket.sent).toEqual([{ command: Command.ADVANCE, value: 50 }]);
  });

  test("holding a bound key resends its command every 100 ms", () => {
    window.dispatchEvent(new KeyboardEvent("keydown", { code: "KeyW" }));
    vi.advanceTimersByTime(250);

    expect(socket.sent).toEqual([
      { command: Command.ADVANCE, value: 50 },
      { command: Command.ADVANCE, value: 50 },
      { command: Command.ADVANCE, value: 50 },
    ]);
  });

  test("releasing the key sends BRAKE", () => {
    window.dispatchEvent(new KeyboardEvent("keydown", { code: "KeyW" }));
    window.dispatchEvent(new KeyboardEvent("keyup", { code: "KeyW" }));

    expect(socket.sent.at(-1)).toEqual({ command: Command.BRAKE, value: null });
  });

  test("releasing the key stops the resends", () => {
    window.dispatchEvent(new KeyboardEvent("keydown", { code: "KeyW" }));
    window.dispatchEvent(new KeyboardEvent("keyup", { code: "KeyW" }));
    const sentAfterRelease = socket.sent.length;

    vi.advanceTimersByTime(500);

    expect(socket.sent).toHaveLength(sentAfterRelease);
  });

  test.each([
    { kind: "press", repeat: false },
    { kind: "auto-repeat", repeat: true },
  ])("a bound key's $kind does not scroll the page", ({ repeat }) => {
    const event = new KeyboardEvent("keydown", { code: "ArrowDown", repeat, cancelable: true });

    window.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(true);
  });

  test("an unbound key keeps its default action", () => {
    const event = new KeyboardEvent("keydown", { code: "Tab", cancelable: true });

    window.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(false);
  });

  test("an auto-repeat keydown is ignored", () => {
    window.dispatchEvent(new KeyboardEvent("keydown", { code: "KeyW" }));
    window.dispatchEvent(new KeyboardEvent("keydown", { code: "KeyW", repeat: true }));

    expect(socket.sent).toEqual([{ command: Command.ADVANCE, value: 50 }]);
  });

  test("releasing one of two held keys falls back to the other", () => {
    window.dispatchEvent(new KeyboardEvent("keydown", { code: "KeyW" }));
    window.dispatchEvent(new KeyboardEvent("keydown", { code: "KeyA" }));
    window.dispatchEvent(new KeyboardEvent("keyup", { code: "KeyA" }));

    expect(socket.sent.at(-1)).toEqual({ command: Command.ADVANCE, value: 50 });
  });

  test("losing window focus while a key is held sends BRAKE", () => {
    window.dispatchEvent(new KeyboardEvent("keydown", { code: "KeyW" }));
    window.dispatchEvent(new Event("blur"));

    expect(socket.sent.at(-1)).toEqual({ command: Command.BRAKE, value: null });
  });

  test("losing window focus while a key is held stops the resends", () => {
    window.dispatchEvent(new KeyboardEvent("keydown", { code: "KeyW" }));
    window.dispatchEvent(new Event("blur"));
    const sentAfterBlur = socket.sent.length;

    vi.advanceTimersByTime(500);

    expect(socket.sent).toHaveLength(sentAfterBlur);
  });

  test("does not send while the socket isn't open", () => {
    socket.readyState = WebSocket.CONNECTING;

    window.dispatchEvent(new KeyboardEvent("keydown", { code: "KeyW" }));

    expect(socket.sent).toEqual([]);
  });
});

describe("driveStatusText", () => {
  test.each([
    {
      kind: "a refusal",
      reason: "another driver is connected",
      text: "Not driving: another driver is connected",
    },
    {
      kind: "a lost connection",
      reason: "",
      text: "Not driving: lost the connection to the streamer",
    },
  ])("explains $kind", ({ reason, text }) => {
    expect(driveStatusText(new CloseEvent("close", { reason }))).toBe(text);
  });
});
