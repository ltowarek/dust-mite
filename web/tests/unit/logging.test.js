import { SeverityNumber } from "@opentelemetry/api-logs";
import { describe, expect, test } from "vitest";
import { buildUncaughtErrorLogRecord, buildWsAbnormalCloseLogRecord } from "../../src/logging.js";

describe("buildUncaughtErrorLogRecord", () => {
  test("builds a record from an Error's name, message, and stack", () => {
    const error = new TypeError("boom");

    const record = buildUncaughtErrorLogRecord({
      message: "Uncaught TypeError: boom",
      filename: "https://example.test/app.js",
      lineno: 42,
      colno: 7,
      error,
    });

    expect(record.severityNumber).toBe(SeverityNumber.ERROR);
    expect(record.severityText).toBe("ERROR");
    expect(record.body).toBe("Uncaught TypeError: boom");
    expect(record.attributes).toMatchObject({
      "exception.type": "TypeError",
      "exception.message": "boom",
      "exception.stacktrace": error.stack,
      "code.filepath": "https://example.test/app.js",
      "code.lineno": 42,
      "code.colno": 7,
    });
  });

  test("falls back to the error's message when no top-level message is given", () => {
    const record = buildUncaughtErrorLogRecord({
      error: new Error("only the error has a message"),
    });

    expect(record.body).toBe("only the error has a message");
  });

  test("falls back to a generic body when neither message nor error is given", () => {
    const record = buildUncaughtErrorLogRecord({});

    expect(record.body).toBe("Uncaught error");
  });

  test("omits attributes that have no value", () => {
    const record = buildUncaughtErrorLogRecord({ message: "plain message" });

    expect(record.attributes).toEqual({});
  });
});

describe("buildWsAbnormalCloseLogRecord", () => {
  test("builds an abnormal-close record with code and reason", () => {
    const record = buildWsAbnormalCloseLogRecord({
      url: "ws://localhost:8765",
      code: 1006,
      reason: "connection lost",
      wasClean: false,
    });

    expect(record.severityNumber).toBe(SeverityNumber.ERROR);
    expect(record.body).toBe("WebSocket closed abnormally: code=1006, reason=connection lost");
    expect(record.attributes).toEqual({
      "ws.url": "ws://localhost:8765",
      "network.protocol.name": "websocket",
      "ws.close.code": 1006,
      "ws.close.reason": "connection lost",
      "ws.close.wasClean": false,
    });
  });

  test("omits the reason attribute when the close carries none", () => {
    const record = buildWsAbnormalCloseLogRecord({
      url: "ws://localhost:8765",
      code: 1006,
      reason: "",
      wasClean: false,
    });

    expect(record.body).toBe("WebSocket closed abnormally: code=1006");
    expect(record.attributes).not.toHaveProperty("ws.close.reason");
  });
});
