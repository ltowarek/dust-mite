import { Command } from "./command.js";
import { HeldKeyStack, readGamepadCommand } from "./input.js";

// Well under the car's drive-command watchdog.
const SEND_INTERVAL_MS = 100;

/**
 * Drives the car from keyboard and Gamepad API input over `socket`.
 *
 * Sends the current command every SEND_INTERVAL_MS while one is held, then
 * BRAKE once when it is released, and nothing while parked. The keyboard is
 * read from keydown/keyup and the gamepad is polled once per animation frame;
 * when both are active, the keyboard wins.
 */
export class DriveController {
  constructor(socket, windowRef = window, navigatorRef = navigator) {
    this._socket = socket;
    this._window = windowRef;
    this._navigator = navigatorRef;

    this._keys = new HeldKeyStack();
    this._keyboardCommand = null;
    this._gamepadCommand = null;
    this._gamepadIndex = null;
    this._currentCommand = null;
    this._sendIntervalId = null;
    this._rafId = null;

    this._onKeyDown = this._onKeyDown.bind(this);
    this._onKeyUp = this._onKeyUp.bind(this);
    this._onBlur = this._onBlur.bind(this);
    this._onGamepadConnected = this._onGamepadConnected.bind(this);
    this._onGamepadDisconnected = this._onGamepadDisconnected.bind(this);
    this._pollGamepad = this._pollGamepad.bind(this);
  }

  start() {
    this._window.addEventListener("keydown", this._onKeyDown);
    this._window.addEventListener("keyup", this._onKeyUp);
    this._window.addEventListener("blur", this._onBlur);
    this._window.addEventListener("gamepadconnected", this._onGamepadConnected);
    this._window.addEventListener("gamepaddisconnected", this._onGamepadDisconnected);
    this._rafId = this._window.requestAnimationFrame(this._pollGamepad);
  }

  stop() {
    this._window.removeEventListener("keydown", this._onKeyDown);
    this._window.removeEventListener("keyup", this._onKeyUp);
    this._window.removeEventListener("blur", this._onBlur);
    this._window.removeEventListener("gamepadconnected", this._onGamepadConnected);
    this._window.removeEventListener("gamepaddisconnected", this._onGamepadDisconnected);
    if (this._rafId !== null) {
      this._window.cancelAnimationFrame(this._rafId);
      this._rafId = null;
    }
    this._stopSending();
  }

  _onKeyDown(event) {
    if (event.repeat) {
      return;
    }
    this._keys.press(event.code);
    this._keyboardCommand = this._keys.current();
    this._recompute();
  }

  _onKeyUp(event) {
    this._keys.release(event.code);
    this._keyboardCommand = this._keys.current();
    this._recompute();
  }

  _onBlur() {
    this._keys.clear();
    this._keyboardCommand = null;
    this._recompute();
  }

  _onGamepadConnected(event) {
    this._gamepadIndex = event.gamepad.index;
  }

  _onGamepadDisconnected(event) {
    if (event.gamepad.index === this._gamepadIndex) {
      this._gamepadIndex = null;
      this._gamepadCommand = null;
      this._recompute();
    }
  }

  _pollGamepad() {
    if (this._gamepadIndex !== null) {
      const gamepad = this._navigator.getGamepads()[this._gamepadIndex];
      this._gamepadCommand = gamepad ? readGamepadCommand(gamepad) : null;
      this._recompute();
    }
    this._rafId = this._window.requestAnimationFrame(this._pollGamepad);
  }

  _recompute() {
    this._setCurrentCommand(this._keyboardCommand ?? this._gamepadCommand);
  }

  _setCurrentCommand(next) {
    const wasActive = this._currentCommand !== null;
    this._currentCommand = next;
    const isActive = next !== null;

    if (isActive && !wasActive) {
      this._startSending();
    } else if (!isActive && wasActive) {
      this._stopSending();
      this._send({ command: Command.BRAKE, value: null });
    }
  }

  _startSending() {
    this._send(this._currentCommand);
    this._sendIntervalId = this._window.setInterval(() => {
      this._send(this._currentCommand);
    }, SEND_INTERVAL_MS);
  }

  _stopSending() {
    if (this._sendIntervalId !== null) {
      this._window.clearInterval(this._sendIntervalId);
      this._sendIntervalId = null;
    }
  }

  _send(command) {
    if (this._socket.readyState !== WebSocket.OPEN) {
      return;
    }
    this._socket.send(JSON.stringify(command));
  }
}
