import { Command } from "./command.js";

// Keys send a fixed value, like the D-pad in the controller CLI's DualSense backend.
export const KEY_BINDINGS = {
  KeyW: { command: Command.ADVANCE, value: 50 },
  KeyS: { command: Command.RETREAT, value: 50 },
  KeyA: { command: Command.TURN_LEFT, value: 50 },
  KeyD: { command: Command.TURN_RIGHT, value: 50 },
};

function interpolate(value, inMin, inMax, outMin, outMax) {
  return ((value - inMin) * (outMax - outMin)) / (inMax - inMin) + outMin;
}

/**
 * Tracks which bound keys are currently held, most-recently-pressed last.
 *
 * Releasing the top key falls back to the most recently pressed key that is
 * still held, instead of dropping straight to no command.
 */
export class HeldKeyStack {
  constructor() {
    this._stack = [];
  }

  press(code) {
    if (!(code in KEY_BINDINGS)) {
      return;
    }
    this._stack = this._stack.filter((held) => held !== code);
    this._stack.push(code);
  }

  release(code) {
    this._stack = this._stack.filter((held) => held !== code);
  }

  clear() {
    this._stack = [];
  }

  /** Return the bound command for the most recently pressed held key, or null. */
  current() {
    if (this._stack.length === 0) {
      return null;
    }
    return KEY_BINDINGS[this._stack[this._stack.length - 1]];
  }
}

const GAMEPAD_FIXED_VALUE = 50;
const GAMEPAD_ANALOG_DEAD_ZONE = 0.1;
const GAMEPAD_TRIGGER_DEAD_ZONE = 0.05;

// Standard Gamepad API mapping (W3C): axes[0..3] are the left/right sticks'
// X/Y, buttons[6]/[7] are the L2/R2 analog triggers, buttons[12..15] are the D-pad.
const GAMEPAD_BUTTON_DPAD_UP = 12;
const GAMEPAD_BUTTON_DPAD_DOWN = 13;
const GAMEPAD_BUTTON_DPAD_LEFT = 14;
const GAMEPAD_BUTTON_DPAD_RIGHT = 15;
const GAMEPAD_BUTTON_R2 = 7;

/**
 * Read the current command from a Gamepad API `Gamepad` snapshot, or null if
 * every control is at rest.
 *
 * Only one command can be sent at a time, so controls are checked in the same
 * order as the controller CLI's DualSense backend: D-pad, left stick (turn),
 * right stick (pan/tilt), then the R2 trigger (advance).
 */
export function readGamepadCommand(gamepad) {
  const [lx, , rx, ry] = gamepad.axes;

  if (gamepad.buttons[GAMEPAD_BUTTON_DPAD_UP]?.pressed) {
    return { command: Command.ADVANCE, value: GAMEPAD_FIXED_VALUE };
  }
  if (gamepad.buttons[GAMEPAD_BUTTON_DPAD_RIGHT]?.pressed) {
    return { command: Command.TURN_RIGHT, value: GAMEPAD_FIXED_VALUE };
  }
  if (gamepad.buttons[GAMEPAD_BUTTON_DPAD_DOWN]?.pressed) {
    return { command: Command.RETREAT, value: GAMEPAD_FIXED_VALUE };
  }
  if (gamepad.buttons[GAMEPAD_BUTTON_DPAD_LEFT]?.pressed) {
    return { command: Command.TURN_LEFT, value: GAMEPAD_FIXED_VALUE };
  }

  if (Math.abs(lx) > GAMEPAD_ANALOG_DEAD_ZONE) {
    return lx < 0
      ? { command: Command.TURN_LEFT, value: Math.round(interpolate(-lx, 0, 1, 0, 100)) }
      : { command: Command.TURN_RIGHT, value: Math.round(interpolate(lx, 0, 1, 0, 100)) };
  }
  if (Math.abs(rx) > GAMEPAD_ANALOG_DEAD_ZONE) {
    return {
      command: Command.LOOK_HORIZONTALLY,
      value: Math.round(interpolate(rx, -1, 1, -90, 90)),
    };
  }
  if (Math.abs(ry) > GAMEPAD_ANALOG_DEAD_ZONE) {
    return {
      command: Command.LOOK_VERTICALLY,
      value: Math.round(interpolate(ry, -1, 1, 90, -90)),
    };
  }

  const r2 = gamepad.buttons[GAMEPAD_BUTTON_R2]?.value ?? 0;
  if (r2 > GAMEPAD_TRIGGER_DEAD_ZONE) {
    return { command: Command.ADVANCE, value: Math.round(interpolate(r2, 0, 1, 0, 100)) };
  }

  return null;
}
