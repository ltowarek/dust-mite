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
    stack.press("KeyW"); // e.g. a duplicate press event, not host auto-repeat (callers filter that)
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

function fakeGamepad({ axes = [0, 0, 0, 0], buttons = {} } = {}) {
  const defaultButtons = Array.from({ length: 17 }, () => ({ pressed: false, value: 0 }));
  for (const [index, button] of Object.entries(buttons)) {
    defaultButtons[index] = { pressed: false, value: 0, ...button };
  }
  return { axes, buttons: defaultButtons };
}

describe("readGamepadCommand", () => {
  test("returns null when every axis and button is at rest", () => {
    expect(readGamepadCommand(fakeGamepad())).toBeNull();
  });

  test("D-pad up advances at the fixed value", () => {
    const gamepad = fakeGamepad({ buttons: { 12: { pressed: true } } });

    expect(readGamepadCommand(gamepad)).toEqual({ command: Command.ADVANCE, value: 50 });
  });

  test("D-pad down retreats, left/right turn, all at the fixed value", () => {
    expect(readGamepadCommand(fakeGamepad({ buttons: { 13: { pressed: true } } }))).toEqual({
      command: Command.RETREAT,
      value: 50,
    });
    expect(readGamepadCommand(fakeGamepad({ buttons: { 14: { pressed: true } } }))).toEqual({
      command: Command.TURN_LEFT,
      value: 50,
    });
    expect(readGamepadCommand(fakeGamepad({ buttons: { 15: { pressed: true } } }))).toEqual({
      command: Command.TURN_RIGHT,
      value: 50,
    });
  });

  test("left stick X past the dead zone turns proportionally", () => {
    expect(readGamepadCommand(fakeGamepad({ axes: [-1, 0, 0, 0] }))).toEqual({
      command: Command.TURN_LEFT,
      value: 100,
    });
    expect(readGamepadCommand(fakeGamepad({ axes: [1, 0, 0, 0] }))).toEqual({
      command: Command.TURN_RIGHT,
      value: 100,
    });
  });

  test("left stick X within the dead zone is ignored", () => {
    expect(readGamepadCommand(fakeGamepad({ axes: [0.05, 0, 0, 0] }))).toBeNull();
  });

  test("right stick pans and tilts the camera", () => {
    expect(readGamepadCommand(fakeGamepad({ axes: [0, 0, 1, 0] }))).toEqual({
      command: Command.LOOK_HORIZONTALLY,
      value: 90,
    });
    expect(readGamepadCommand(fakeGamepad({ axes: [0, 0, 0, -1] }))).toEqual({
      command: Command.LOOK_VERTICALLY,
      value: 90,
    });
  });

  test("R2 trigger advances proportionally to how far it's pulled", () => {
    const gamepad = fakeGamepad({ buttons: { 7: { value: 0.5 } } });

    expect(readGamepadCommand(gamepad)).toEqual({ command: Command.ADVANCE, value: 50 });
  });

  test("D-pad takes priority over the left stick", () => {
    const gamepad = fakeGamepad({ axes: [1, 0, 0, 0], buttons: { 12: { pressed: true } } });

    expect(readGamepadCommand(gamepad)).toEqual({ command: Command.ADVANCE, value: 50 });
  });

  test("the left stick takes priority over the right stick and triggers", () => {
    const gamepad = fakeGamepad({ axes: [1, 0, 1, 0], buttons: { 7: { value: 1 } } });

    expect(readGamepadCommand(gamepad).command).toBe(Command.TURN_RIGHT);
  });
});
