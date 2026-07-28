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
  ReposResponse,
  SessionsResponse,
} from "./types";

/**
 * The repo root threaded into every board/card/mutation call below (the
 * repo selector's single choke point — see `setActiveRoot`). `null` means
 * "no selection yet" / "use the dashboard's own launch root", which is
 * exactly the pre-selector default behaviour: every wrapper below omits
 * the `root` query param entirely in that case.
 */
let activeRoot: string | null = null;

/**
 * Sets the root every subsequent API call threads through as `?root=...`.
 * The repo selector (App.tsx) is the SOLE caller — no other module needs to
 * know a multi-repo selection even exists, matching this module's existing
 * charter as the sole holder of endpoint URLs/shapes.
 */
export function setActiveRoot(root: string | null): void {
  activeRoot = root;
}

/** Appends `?root=...` (or `&root=...` if the url already has a query
 * string) when a root is active; otherwise returns `url` unchanged. */
function withRoot(url: string): string {
  if (activeRoot === null) return url;
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}root=${encodeURIComponent(activeRoot)}`;
}

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
  return request<BoardResponse>("GET", withRoot("/api/board"));
}

/** Repo discovery — always global (never itself root-scoped); the backend
 * marks whichever entry is its own launch root with `current: true`. */
export function getRepos(): Promise<ReposResponse> {
  return request<ReposResponse>("GET", "/api/repos");
}

export function getSessions(): Promise<SessionsResponse> {
  return request<SessionsResponse>("GET", "/api/sessions");
}

export function getCard(id: string): Promise<CardDetail> {
  return request<CardDetail>("GET", withRoot(`/api/card/${id}`));
}

export function setOrder(id: string, order: number): Promise<BoardResponse> {
  return request<BoardResponse>("POST", withRoot(`/api/card/${id}/order`), {
    order,
  });
}

export function setPriority(
  id: string,
  priority: string | null
): Promise<BoardResponse> {
  return request<BoardResponse>("POST", withRoot(`/api/card/${id}/priority`), {
    priority,
  });
}

export function setParent(
  id: string,
  parent: string | null
): Promise<BoardResponse> {
  return request<BoardResponse>("POST", withRoot(`/api/card/${id}/parent`), {
    parent,
  });
}

export function setDepends(
  id: string,
  body: DependsBody
): Promise<BoardResponse> {
  return request<BoardResponse>(
    "POST",
    withRoot(`/api/card/${id}/depends`),
    body
  );
}

export function park(id: string): Promise<BoardResponse> {
  return request<BoardResponse>("POST", withRoot(`/api/card/${id}/park`));
}

export function unpark(id: string): Promise<BoardResponse> {
  return request<BoardResponse>("POST", withRoot(`/api/card/${id}/unpark`));
}

export function move(id: string, body: MoveBody): Promise<BoardResponse> {
  return request<BoardResponse>("POST", withRoot(`/api/card/${id}/move`), body);
}

export function setThreshold(value: number): Promise<BoardResponse> {
  return request<BoardResponse>("POST", withRoot("/api/config/threshold"), {
    value,
  });
}

export function claimCard(id: string, sessionId: string): Promise<BoardResponse> {
  return request<BoardResponse>("POST", withRoot(`/api/card/${id}/claim`), {
    session_id: sessionId,
  });
}

export function unclaimCard(id: string): Promise<BoardResponse> {
  return request<BoardResponse>("POST", withRoot(`/api/card/${id}/unclaim`));
}
