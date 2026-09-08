import { describe, expect, it } from "vitest";

import { MAX_RETRIES, backoffSeconds, classifyFailure, isRetryable } from "./retry";
import { ApiError } from "../api/client";

describe("backoffSeconds", () => {
  it("doubles from 2s and caps at 30 — a minute of trying across the budget", () => {
    const waits = Array.from({ length: MAX_RETRIES }, (_, i) => backoffSeconds(i + 1));
    expect(waits).toEqual([2, 4, 8, 16, 30]);
    expect(waits.reduce((a, b) => a + b)).toBe(60);
  });

  it("never returns less than the first step, however it is called", () => {
    expect(backoffSeconds(0)).toBe(2);
    expect(backoffSeconds(-3)).toBe(2);
  });
});

describe("classifyFailure", () => {
  it("treats a request that never reached the server as retryable", () => {
    // The browser's own shape for offline / server-down: no status at all.
    expect(classifyFailure(new TypeError("Failed to fetch"))).toBe("retryable");
  });

  it("calls a refused dashboard token terminal, not retryable", () => {
    // The whole point: an identical retry can only be refused identically.
    expect(classifyFailure(new ApiError(401, "missing or invalid dashboard token"))).toBe("auth");
    expect(classifyFailure(new ApiError(403, "forbidden"))).toBe("auth");
    expect(isRetryable(classifyFailure(new ApiError(401, "nope")))).toBe(false);
  });

  it("retries a server that is merely unwell", () => {
    for (const status of [500, 502, 503, 504]) {
      expect(classifyFailure(new ApiError(status, "boom"))).toBe("retryable");
    }
  });

  it("retries the two statuses that explicitly mean come back later", () => {
    expect(classifyFailure(new ApiError(408, "timeout"))).toBe("retryable");
    expect(classifyFailure(new ApiError(429, "slow down"))).toBe("retryable");
  });

  it("does not retry a request the server will never accept", () => {
    expect(classifyFailure(new ApiError(400, "unknown root"))).toBe("rejected");
    expect(classifyFailure(new ApiError(404, "no card"))).toBe("rejected");
    expect(isRetryable(classifyFailure(new ApiError(400, "nope")))).toBe(false);
  });

  it("recognises a cancel as a deliberate stop rather than a failure", () => {
    const aborted = new Error("aborted");
    aborted.name = "AbortError";
    expect(classifyFailure(aborted)).toBe("aborted");
    expect(isRetryable("aborted")).toBe(false);
  });

  it("reads the status structurally, so a re-thrown error still classifies", () => {
    // Not an ApiError instance — the class identity is deliberately not the
    // thing being tested for, so an error that crossed a boundary still works.
    expect(classifyFailure({ status: 401, message: "nope" })).toBe("auth");
  });
});
