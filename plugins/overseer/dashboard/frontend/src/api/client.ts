/**
 * The SOLE module that knows overseer dashboard endpoint URLs/shapes.
 * Every call is same-origin (`/api/*`). No other module should embed a URL —
 * import the wrappers below instead.
 */
import type {
  BoardResponse,
  CardDetail,
  ClearResponse,
  CreateCardBody,
  CreateCardResponse,
  DependsBody,
  EditCardBody,
  MoveBody,
  ReposResponse,
  SessionsResponse,
} from "./types";

/** localStorage key holding the operator-pasted dashboard auth token
 * (see `authHeaders`/`request` below) — gated backend deployments 401
 * until this is set; ungated deployments (the default) never 401, so
 * this key stays empty and every request below is header-free. */
const TOKEN_KEY = "overseer_dashboard_token";

/** `X-Overseer-Token` header, present only when a token has been stored —
 * the ungated-by-default backend never requires it, so the happy path
 * (empty localStorage) sends no auth header at all. */
function authHeaders(): Record<string, string> {
  const tok = localStorage.getItem(TOKEN_KEY);
  return tok ? { "X-Overseer-Token": tok } : {};
}

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
 * Called by the repo-scoped data hooks (`useBoard`, `useSessions`) at the
 * start of the same effect that fires their fetch, always with the SAME
 * App-level `activeRoot` state — no other module needs to know a
 * multi-repo selection even exists, matching this module's existing
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
 *
 * Auth (WF-... token gate): every request carries `X-Overseer-Token` when
 * one is stored (`authHeaders`), which is a no-op header-wise on the
 * ungated-by-default backend. On a 401 (gate active, no/expired token) we
 * prompt once via `window.prompt`, store whatever the operator pastes, and
 * retry the SAME request exactly once; a cancelled prompt (`null`) falls
 * through to the normal non-ok handling below without a second fetch.
 */
async function request<T>(
  method: "GET" | "POST",
  url: string,
  body?: unknown
): Promise<T> {
  const send = async (): Promise<Response> => {
    const headers: Record<string, string> = { ...authHeaders() };
    const init: RequestInit = { method, headers };
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    return fetch(url, init);
  };

  let res = await send();

  if (res.status === 401) {
    const tok = window.prompt("This dashboard requires a token. Paste it:");
    if (tok) {
      localStorage.setItem(TOKEN_KEY, tok);
      res = await send();
    }
  }

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

/** Census sessions, scoped to the active root (WF-031) — same `withRoot`
 * choke point `getBoard` uses, so switching repos re-scopes the Party the
 * same instant it re-scopes the board. */
export function getSessions(): Promise<SessionsResponse> {
  return request<SessionsResponse>("GET", withRoot("/api/sessions"));
}

export function getCard(id: string): Promise<CardDetail> {
  return request<CardDetail>("GET", withRoot(`/api/card/${id}`));
}

/** Creates a new card. Returns the usual board payload plus the new card's
 * id (`card_id`) so callers can e.g. navigate straight to it. */
export function createCard(body: CreateCardBody): Promise<CreateCardResponse> {
  return request<CreateCardResponse>("POST", withRoot("/api/card"), body);
}

/** Edits an existing card's title and/or body markdown. */
export function editCard(id: string, body: EditCardBody): Promise<BoardResponse> {
  return request<BoardResponse>("POST", withRoot(`/api/card/${id}`), body);
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

/** Pulls all live children of an epic into the epic's own column (F9,
 * WF-066) — token-gated backend endpoint added in Task 5. */
export function pullChildren(id: string): Promise<BoardResponse> {
  return request<BoardResponse>(
    "POST",
    withRoot(`/api/card/${id}/pull-children`)
  );
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

/** Persists a card's labels (F1, WF-058) — full-replace semantics, same as
 * the backend's `POST /api/card/{id}/labels`. */
export function setLabels(id: string, labels: string[]): Promise<BoardResponse> {
  return request<BoardResponse>("POST", withRoot(`/api/card/${id}/labels`), {
    labels,
  });
}

/** Sets (or, with `color: null`, clears) a label's entry in the F10
 * editable colour registry (WF-067) — `board.label_colors`. `color` is one
 * of `labelColor.ts`'s `PALETTE_KEYS`, or `null` to reset the label back to
 * its curated-palette hash default. Root-scoped like the other card/board
 * mutations (`setLabels`, `setThreshold`) — the backend's `/api/labels/colors`
 * takes the same `root` query param. */
export function setLabelColor(
  name: string,
  color: string | null
): Promise<BoardResponse> {
  return request<BoardResponse>("POST", withRoot("/api/labels/colors"), {
    name,
    color,
  });
}

/** Clear-data action (dashboard settings). Deliberately NOT `withRoot`-scoped
 * — the clear target is the modal's explicitly selected repo, not whatever
 * root happens to be active, so `root` is threaded through the body instead. */
export function clearRepo(
  root: string,
  scope: "cards" | "repo"
): Promise<ClearResponse> {
  return request<ClearResponse>("POST", "/api/repo/clear", { root, scope });
}
