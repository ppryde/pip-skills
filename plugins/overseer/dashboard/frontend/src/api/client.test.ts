import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as client from "./client";
import type {
  BoardResponse,
  CardDetail,
  ClearResponse,
  SessionsResponse,
} from "./types";

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
  created: "2026-07-01",
  updated: "2026-07-01T10:00",
  checklist: [],
  labels: [],
  links: [],
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
    localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    // `activeRoot` is module-level state (the repo selector's single choke
    // point) — reset it so a root set by one test never leaks into the next.
    client.setActiveRoot(null);
    localStorage.clear();
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

  it("getRepos() GETs /api/repos and returns the parsed response", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        repos: [
          { label: "repo-a", root: "/a", current: true },
          { label: "repo-b", root: "/b", current: false },
        ],
      })
    );

    const result = await client.getRepos();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/repos");
    expect(init?.method ?? "GET").toBe("GET");
    expect(result.repos).toHaveLength(2);
  });

  it("getRepos() never carries a root query param, even when one is active", async () => {
    client.setActiveRoot("/some/repo");
    fetchMock.mockResolvedValueOnce(jsonResponse({ repos: [] }));

    await client.getRepos();

    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/repos");
  });

  it("setActiveRoot(root) threads ?root=... into getBoard()", async () => {
    client.setActiveRoot("/path/to/repo");
    fetchMock.mockResolvedValueOnce(jsonResponse(boardResponse));

    await client.getBoard();

    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/board?root=%2Fpath%2Fto%2Frepo");
  });

  it("setActiveRoot(null) omits the root query param entirely", async () => {
    client.setActiveRoot("/path/to/repo");
    client.setActiveRoot(null);
    fetchMock.mockResolvedValueOnce(jsonResponse(boardResponse));

    await client.getBoard();

    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/board");
  });

  it("threads the active root into a mutation call too", async () => {
    client.setActiveRoot("/repo-b");
    fetchMock.mockResolvedValueOnce(jsonResponse(boardResponse));

    await client.setOrder("WF-1", 3);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/card/WF-1/order?root=%2Frepo-b");
    expect(JSON.parse(init.body)).toEqual({ order: 3 });
  });

  it("getSessions() GETs /api/sessions and returns the parsed response", async () => {
    const sessionsResponse: SessionsResponse = {
      sessions: [
        {
          id: "s1",
          worktree_cwd: "/path/to/work",
          updated_at: 1234567890,
          stale: false,
          session_name: "night-shift",
          model: "Opus",
          pct: 44,
          pr: { number: 22, url: "http://pr/22", review_state: "pending" },
        },
      ],
    };
    fetchMock.mockResolvedValueOnce(jsonResponse(sessionsResponse));

    const result = await client.getSessions();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/sessions");
    expect(init?.method ?? "GET").toBe("GET");
    expect(result).toEqual(sessionsResponse);
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

  it("pullChildren(id) POSTs to /api/card/{id}/pull-children (F9, WF-066)", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(boardResponse));

    const result = await client.pullChildren("WF-1");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/card/WF-1/pull-children");
    expect(init.method).toBe("POST");
    expect(result).toEqual(boardResponse);
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

  it("claimCard(id, sessionId) POSTs {session_id} to /api/card/{id}/claim", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(boardResponse));

    const result = await client.claimCard("WF-1", "sess-1");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/card/WF-1/claim");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ session_id: "sess-1" });
    expect(result).toEqual(boardResponse);
  });

  it("unclaimCard(id) POSTs (no body) to /api/card/{id}/unclaim", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(boardResponse));

    const result = await client.unclaimCard("WF-1");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/card/WF-1/unclaim");
    expect(init.method).toBe("POST");
    expect(init.body).toBeUndefined();
    expect(result).toEqual(boardResponse);
  });

  it("setLabels(id, labels) POSTs {labels} to /api/card/{id}/labels", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(boardResponse));

    const result = await client.setLabels("WF-1", ["policy", "architecture"]);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/card/WF-1/labels");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      labels: ["policy", "architecture"],
    });
    expect(result).toEqual(boardResponse);
  });

  it("setLabels(id, []) sends {labels: []} (clear-all)", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(boardResponse));

    await client.setLabels("WF-1", []);

    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(init.body)).toEqual({ labels: [] });
  });

  it("threads the active root into setLabels() too", async () => {
    client.setActiveRoot("/repo-b");
    fetchMock.mockResolvedValueOnce(jsonResponse(boardResponse));

    await client.setLabels("WF-1", ["policy"]);

    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/card/WF-1/labels?root=%2Frepo-b");
  });

  it("createCard(body) POSTs body to /api/card and returns card_id", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ ...boardResponse, card_id: "WF-9" })
    );

    const result = await client.createCard({ title: "New", complexity: "M" });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/card");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ title: "New", complexity: "M" });
    expect(result.card_id).toBe("WF-9");
  });

  it("threads the active root into createCard() too", async () => {
    client.setActiveRoot("/repo-b");
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ ...boardResponse, card_id: "WF-9" })
    );

    await client.createCard({ title: "New" });

    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/card?root=%2Frepo-b");
  });

  it("editCard(id, body) POSTs {title,body} to /api/card/{id}", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(boardResponse));

    const result = await client.editCard("WF-1", { title: "T", body: "B" });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/card/WF-1");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ title: "T", body: "B" });
    expect(result).toEqual(boardResponse);
  });

  it("sends no X-Overseer-Token header when localStorage is empty", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(boardResponse));

    await client.park("WF-1");

    const [, init] = fetchMock.mock.calls[0];
    expect((init.headers as Record<string, string>)["X-Overseer-Token"]).toBeUndefined();
  });

  it("sends X-Overseer-Token header when one is stored", async () => {
    localStorage.setItem("overseer_dashboard_token", "tok-1");
    fetchMock.mockResolvedValueOnce(jsonResponse(boardResponse));

    await client.park("WF-1");

    const [, init] = fetchMock.mock.calls[0];
    expect((init.headers as Record<string, string>)["X-Overseer-Token"]).toBe("tok-1");
  });

  it("on 401 prompts for a token, stores it, and retries once", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ detail: "x" }, 401))
      .mockResolvedValueOnce(jsonResponse(boardResponse));
    vi.spyOn(window, "prompt").mockReturnValue("pasted-tok");

    const result = await client.park("WF-1");

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(localStorage.getItem("overseer_dashboard_token")).toBe("pasted-tok");
    const [, retryInit] = fetchMock.mock.calls[1];
    expect((retryInit.headers as Record<string, string>)["X-Overseer-Token"]).toBe(
      "pasted-tok"
    );
    expect(result).toEqual(boardResponse);
  });

  it("on 401 with prompt cancelled (null) does not retry and throws", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "unauthorized" }, 401));
    vi.spyOn(window, "prompt").mockReturnValue(null);

    await expect(client.park("WF-1")).rejects.toThrow("unauthorized");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem("overseer_dashboard_token")).toBeNull();
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

  it("clearRepo(root, scope) POSTs {root, scope} to /api/repo/clear and returns the parsed response", async () => {
    const clearResponse: ClearResponse = {
      scope: "repo",
      backup_path: "/tmp/snap",
      removed: { folder: "/x", existed: true },
      label: "demo",
      noop: false,
    };
    fetchMock.mockResolvedValueOnce(jsonResponse(clearResponse));

    const result = await client.clearRepo("/repos/demo", "repo");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/repo/clear");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ root: "/repos/demo", scope: "repo" });
    expect(result).toEqual(clearResponse);
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
