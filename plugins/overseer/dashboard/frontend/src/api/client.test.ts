import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as client from "./client";
import type { BoardResponse, CardDetail } from "./types";

const boardResponse: BoardResponse = {
  board: { project: {}, cards: [], sprints: [], quarantined: [] },
  context: { pct: 42, threshold: 80 },
  limits: null,
};

const cardDetail: CardDetail = {
  id: "WF-1",
  title: "Do the thing",
  status: "planned",
  stage: null,
  complexity: "S",
  priority: null,
  sprint: null,
  parent: null,
  depends_on: [],
  order: 10,
  budget: { estimate: null, actual: 0 },
  is_epic: false,
  ready: true,
  rollup: null,
  checklist: [],
  sections: { "## Goal": "Ship it" },
  body: "full markdown body",
};

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Error",
    json: async () => body,
  } as Response;
}

describe("api/client", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("getBoard() GETs /api/board and returns the parsed response", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(boardResponse));

    const result = await client.getBoard();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/board");
    expect(init?.method ?? "GET").toBe("GET");
    expect(result).toEqual(boardResponse);
  });

  it("getCard(id) GETs /api/card/{id} and returns the parsed response", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(cardDetail));

    const result = await client.getCard("WF-1");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/card/WF-1");
    expect(init?.method ?? "GET").toBe("GET");
    expect(result).toEqual(cardDetail);
  });

  it("setOrder(id, order) POSTs {order} to /api/card/{id}/order", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(boardResponse));

    const result = await client.setOrder("WF-1", 20);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/card/WF-1/order");
    expect(init.method).toBe("POST");
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body)).toEqual({ order: 20 });
    expect(result).toEqual(boardResponse);
  });

  it("setPriority(id, priority) POSTs {priority} to /api/card/{id}/priority", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(boardResponse));

    await client.setPriority("WF-1", "P0");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/card/WF-1/priority");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ priority: "P0" });
  });

  it("setPriority(id, null) sends {priority: null} (null-clear)", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(boardResponse));

    await client.setPriority("WF-1", null);

    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body)).toEqual({ priority: null });
  });

  it("setParent(id, parent) POSTs {parent} to /api/card/{id}/parent", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(boardResponse));

    await client.setParent("WF-1", "WF-epic");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/card/WF-1/parent");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ parent: "WF-epic" });
  });

  it("setParent(id, null) sends {parent: null} (null-clear)", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(boardResponse));

    await client.setParent("WF-1", null);

    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body)).toEqual({ parent: null });
  });

  it("setDepends(id, {on}) POSTs {on} to /api/card/{id}/depends", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(boardResponse));

    await client.setDepends("WF-1", { on: "WF-1" });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/card/WF-1/depends");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ on: "WF-1" });
  });

  it("setDepends(id, {off}) POSTs {off} to /api/card/{id}/depends", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(boardResponse));

    await client.setDepends("WF-1", { off: "WF-2" });

    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body)).toEqual({ off: "WF-2" });
  });

  it("park(id) POSTs to /api/card/{id}/park", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(boardResponse));

    const result = await client.park("WF-1");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/card/WF-1/park");
    expect(init.method).toBe("POST");
    expect(result).toEqual(boardResponse);
  });

  it("unpark(id) POSTs to /api/card/{id}/unpark", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(boardResponse));

    await client.unpark("WF-1");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/card/WF-1/unpark");
    expect(init.method).toBe("POST");
  });

  it("move(id, {stage}) POSTs {stage} to /api/card/{id}/move", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(boardResponse));

    await client.move("WF-1", { stage: "implementation" });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/card/WF-1/move");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ stage: "implementation" });
  });

  it("move(id, {status, reason}) POSTs {status, reason} to /api/card/{id}/move", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(boardResponse));

    await client.move("WF-1", { status: "blocked", reason: "x" });

    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body)).toEqual({ status: "blocked", reason: "x" });
  });

  it("setThreshold(value) POSTs {value} to /api/config/threshold", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(boardResponse));

    const result = await client.setThreshold(75);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/config/threshold");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ value: 75 });
    expect(result).toEqual(boardResponse);
  });

  it("throws an Error with the backend detail message on a non-2xx response", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "nope" }, 400));

    await expect(client.getBoard()).rejects.toThrow("nope");
  });

  it("falls back to statusText when a non-2xx response has no detail", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      json: async () => ({}),
    } as Response);

    // Anchored regex: the thrown message must EQUAL the statusText — a bare
    // string arg to toThrow would only be a substring-containment check.
    await expect(client.getBoard()).rejects.toThrow(/^Internal Server Error$/);
  });
});
