import { describe, expect, test } from "vitest";
import { Command } from "../../src/command.js";
import { HeldKeyStack, readGamepadCommand } from "../../src/input.js";

describe("HeldKeyStack", () => {
  test("reports no current command when nothing is held", () => {
    const stack = new HeldKeyStack();

    expect(stack.current()).toBeNull();
  });

  test("reports the bound command for a single held key", () => {
    const stack = new HeldKeyStack();

    stack.press("KeyW");

    expect(stack.current()).toEqual({ command: Command.ADVANCE, value: 50 });
  });

  test("binds the arrow keys to camera pan and tilt", () => {
    const stack = new HeldKeyStack();

    stack.press("ArrowLeft");

    expect(stack.current()).toEqual({ command: Command.LOOK_HORIZONTALLY, value: -45 });
  });

  test("ignores keys with no binding", () => {
    const stack = new HeldKeyStack();

    stack.press("KeyQ");

    expect(stack.current()).toBeNull();
  });

  test("falls back to the other held key when the top key is released", () => {
    const stack = new HeldKeyStack();

    stack.press("KeyW");
    stack.press("KeyA");
    stack.release("KeyA");

    expect(stack.current()).toEqual({ command: Command.ADVANCE, value: 50 });
  });

  test("reports the most recently pressed key while both are held", () => {
    const stack = new HeldKeyStack();

    stack.press("KeyW");
    stack.press("KeyA");

    expect(stack.current()).toEqual({ command: Command.TURN_LEFT, value: 50 });
  });

  test("reports no current command once every held key is released", () => {
    const stack = new HeldKeyStack();

    stack.press("KeyW");
    stack.release("KeyW");

    expect(stack.current()).toBeNull();
  });

  test("does not double-push a key that repeats without an intervening release", () => {
    const stack = new HeldKeyStack();

    stack.press("KeyW");
    stack.press("KeyA");
    stack.press("KeyW"); // e.g. a duplicate press event, not host key repeat (callers filter that)
    stack.release("KeyW");

    // KeyW's original position is gone, so KeyA (still held) should surface.
    expect(stack.current()).toEqual({ command: Command.TURN_LEFT, value: 50 });
  });

  test("clear() releases every held key", () => {
    const stack = new HeldKeyStack();

    stack.press("KeyW");
    stack.press("KeyA");
    stack.clear();

    expect(stack.current()).toBeNull();
  });
});

function gamepadStub({ axes = [0, 0, 0, 0], buttons = {} } = {}) {
  const defaultButtons = Array.from({ length: 17 }, () => ({ pressed: false, value: 0 }));
  for (const [index, button] of Object.entries(buttons)) {
    defaultButtons[index] = { pressed: false, value: 0, ...button };
  }
  return { axes, buttons: defaultButtons };
}

describe("readGamepadCommand", () => {
  test("returns null when every axis and button is at rest", () => {
    expect(readGamepadCommand(gamepadStub())).toBeNull();
  });

  test.each([
    { direction: "up", button: 12, command: Command.ADVANCE },
    { direction: "down", button: 13, command: Command.RETREAT },
    { direction: "left", button: 14, command: Command.TURN_LEFT },
    { direction: "right", button: 15, command: Command.TURN_RIGHT },
  ])("D-pad $direction sends its command at the fixed value", ({ button, command }) => {
    const gamepad = gamepadStub({ buttons: { [button]: { pressed: true } } });

    expect(readGamepadCommand(gamepad)).toEqual({ command, value: 50 });
  });

  test.each([
    { direction: "left", x: -1, command: Command.TURN_LEFT },
    { direction: "right", x: 1, command: Command.TURN_RIGHT },
  ])("left stick pushed fully $direction turns at full value", ({ x, command }) => {
    const gamepad = gamepadStub({ axes: [x, 0, 0, 0] });

    expect(readGamepadCommand(gamepad)).toEqual({ command, value: 100 });
  });

  test("left stick X within the dead zone is ignored", () => {
    expect(readGamepadCommand(gamepadStub({ axes: [0.05, 0, 0, 0] }))).toBeNull();
  });

  test.each([
    { motion: "right", axes: [0, 0, 1, 0], command: Command.LOOK_HORIZONTALLY },
    { motion: "up", axes: [0, 0, 0, -1], command: Command.LOOK_VERTICALLY },
  ])("right stick pushed fully $motion moves the camera", ({ axes, command }) => {
    const gamepad = gamepadStub({ axes });

    expect(readGamepadCommand(gamepad)).toEqual({ command, value: 90 });
  });

  test("R2 trigger advances proportionally to how far it's pulled", () => {
    const gamepad = gamepadStub({ buttons: { 7: { value: 0.5 } } });

    expect(readGamepadCommand(gamepad)).toEqual({ command: Command.ADVANCE, value: 50 });
  });

  test("D-pad takes priority over the left stick", () => {
    const gamepad = gamepadStub({ axes: [1, 0, 0, 0], buttons: { 12: { pressed: true } } });

    expect(readGamepadCommand(gamepad)).toEqual({ command: Command.ADVANCE, value: 50 });
  });

  test("the left stick takes priority over the right stick and triggers", () => {
    const gamepad = gamepadStub({ axes: [1, 0, 1, 0], buttons: { 7: { value: 1 } } });

    expect(readGamepadCommand(gamepad).command).toBe(Command.TURN_RIGHT);
  });
});
