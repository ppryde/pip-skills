/**
 * The SOLE module that knows overseer dashboard endpoint URLs/shapes.
 * Every call is same-origin (`/api/*`). No other module should embed a URL —
 * import the wrappers below instead.
 */
import type {
  BoardResponse,
  CardDetail,
  DependsBody,
  MoveBody,
  SessionsResponse,
} from "./types";

/**
 * Shared fetch wrapper: sends JSON when a body is given, parses the JSON
 * response, and on a non-2xx status throws an Error carrying the backend's
 * `detail` string (falling back to `res.statusText` when `detail` is
 * absent/unparsable) so callers can surface it to a toast.
 */
async function request<T>(
  method: "GET" | "POST",
  url: string,
  body?: unknown
): Promise<T> {
  const init: RequestInit = { method };
  if (body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }

  const res = await fetch(url, init);

  if (!res.ok) {
    let detail: string | undefined;
    try {
      const errBody = (await res.json()) as { detail?: string };
      detail = errBody?.detail;
    } catch {
      // response wasn't JSON (or was empty) — fall back below.
    }
    throw new Error(detail ?? res.statusText);
  }

  return (await res.json()) as T;
}

export function getBoard(): Promise<BoardResponse> {
  return request<BoardResponse>("GET", "/api/board");
}

export function getSessions(): Promise<SessionsResponse> {
  return request<SessionsResponse>("GET", "/api/sessions");
}

export function getCard(id: string): Promise<CardDetail> {
  return request<CardDetail>("GET", `/api/card/${id}`);
}

export function setOrder(id: string, order: number): Promise<BoardResponse> {
  return request<BoardResponse>("POST", `/api/card/${id}/order`, { order });
}

export function setPriority(
  id: string,
  priority: string | null
): Promise<BoardResponse> {
  return request<BoardResponse>("POST", `/api/card/${id}/priority`, {
    priority,
  });
}

export function setParent(
  id: string,
  parent: string | null
): Promise<BoardResponse> {
  return request<BoardResponse>("POST", `/api/card/${id}/parent`, { parent });
}

export function setDepends(
  id: string,
  body: DependsBody
): Promise<BoardResponse> {
  return request<BoardResponse>("POST", `/api/card/${id}/depends`, body);
}

export function park(id: string): Promise<BoardResponse> {
  return request<BoardResponse>("POST", `/api/card/${id}/park`);
}

export function unpark(id: string): Promise<BoardResponse> {
  return request<BoardResponse>("POST", `/api/card/${id}/unpark`);
}

export function move(id: string, body: MoveBody): Promise<BoardResponse> {
  return request<BoardResponse>("POST", `/api/card/${id}/move`, body);
}

export function setThreshold(value: number): Promise<BoardResponse> {
  return request<BoardResponse>("POST", "/api/config/threshold", { value });
}

export function claimCard(id: string, sessionId: string): Promise<BoardResponse> {
  return request<BoardResponse>("POST", `/api/card/${id}/claim`, {
    session_id: sessionId,
  });
}

export function unclaimCard(id: string): Promise<BoardResponse> {
  return request<BoardResponse>("POST", `/api/card/${id}/unclaim`);
}
