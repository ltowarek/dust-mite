import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { Command } from "../../src/command.js";
import { DriveController } from "../../src/drive.js";

class FakeSocket {
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
    socket = new FakeSocket();
    controller = new DriveController(socket, window, { getGamepads: () => [] });
    controller.start();
  });

  afterEach(() => {
    controller.stop();
    vi.useRealTimers();
  });

  test("holding a bound key sends the command immediately, then every 100 ms", () => {
    window.dispatchEvent(new KeyboardEvent("keydown", { code: "KeyW" }));

    expect(socket.sent).toEqual([{ command: Command.ADVANCE, value: 50 }]);

    vi.advanceTimersByTime(250);

    expect(socket.sent).toEqual([
      { command: Command.ADVANCE, value: 50 },
      { command: Command.ADVANCE, value: 50 },
      { command: Command.ADVANCE, value: 50 },
    ]);
  });

  test("releasing the key sends BRAKE once and the stream stops", () => {
    window.dispatchEvent(new KeyboardEvent("keydown", { code: "KeyW" }));
    window.dispatchEvent(new KeyboardEvent("keyup", { code: "KeyW" }));

    expect(socket.sent.at(-1)).toEqual({ command: Command.BRAKE, value: null });

    const sentAfterRelease = socket.sent.length;
    vi.advanceTimersByTime(500);

    expect(socket.sent).toHaveLength(sentAfterRelease);
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

  test("losing window focus while a key is held stops the car", () => {
    window.dispatchEvent(new KeyboardEvent("keydown", { code: "KeyW" }));
    window.dispatchEvent(new Event("blur"));

    expect(socket.sent.at(-1)).toEqual({ command: Command.BRAKE, value: null });

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
