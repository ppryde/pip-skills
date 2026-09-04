/**
 * Types mirroring the frozen backend contract (see wf005-context.md).
 * This file has NO knowledge of URLs — only shapes. `client.ts` is the
 * only module that knows endpoint paths.
 */

import type { ChecklistEntry } from "../board/checklistWindow";

export type Status =
  | "planned"
  | "in-flight"
  | "blocked"
  | "parked"
  | "done"
  | "abandoned";

export type Stage =
  | "bootstrap"
  | "planning"
  | "plan-review"
  | "implementation"
  | "impl-review"
  | "verification"
  | "awaiting-merge";

export type Priority = "P0" | "P1" | "P2" | "P3" | "P4";

export interface Budget {
  estimate: number | null;
  actual: number;
}

export interface Rollup {
  done: number;
  total: number;
  estimate: number | null;
  actual: number;
}

export interface BoardCard {
  id: string;
  title: string;
  status: Status;
  stage: Stage | null;
  complexity: string | null;
  priority: Priority | null;
  sprint: string | null;
  parent: string | null;
  depends_on: string[];
  order: number;
  budget: Budget;
  is_epic: boolean;
  ready: boolean;
  rollup: Rollup | null;
  /** "%Y-%m-%d", stamped at new-card time — never blank in the real
   * backend contract, but board.ts's `sortLane` tolerates "" defensively
   * (recency parses to epoch 0, sorting last) for hand-built test fixtures
   * and any pre-this-field card the store might still hold. */
  created: string;
  /** ISO minute ("%Y-%m-%dT%H:%M"), stamped by every card mutator — same
   * blank-tolerant contract as `created` above. Drives lane ORDER
   * (recency-first, see board/layout.ts); `order` remains the drag-reorder
   * field but no longer drives display order. */
  updated: string;
  /** Always present (possibly []) — see checklistWindow.ts's ChecklistEntry
   * doc comment for the backend's string-coercion / status quirks. */
  checklist: ChecklistEntry[];
  /** Top-level repo name the card originated from (never the worktree
   * directory name) — absent on cards minted before this label existed. */
  repo?: string;
  /** Git branch the card's work happens on (WF-031 worktree/branch
   * distinction) — absent on cards minted before this label existed, or
   * when the originating worktree carries no resolvable branch. */
  branch?: string;
  /** Claim fields (design spec §5) — census `session_id` holding the card,
   * ISO-minute stamp, and whether a work verb has acked the claim since.
   * Absent/null on never-claimed cards; board/card-detail JSON passthrough,
   * no new backend model work. */
  claimed_by?: string | null;
  claimed_at?: string | null;
  claim_acked?: boolean;
  /** Free-text labels (F1, WF-058) — always present (possibly []), same
   * blank-tolerant contract as `checklist` above. Rendered as coloured chips
   * (see board/labelColor.ts + components/LabelChips.tsx); this is NOT yet
   * the F10 editable colour registry (WF-067, deferred) — no per-project
   * colour configuration, just a stable curated-palette mapping. */
  labels: string[];
  /** Card body markdown — included in the board payload for client-side
   * search (F2). Always present (possibly ""). */
  body: string;
  /** Free-form reference links (F8, WF-065) — always present (possibly []),
   * same blank-tolerant contract as `labels`/`checklist` above. Read-only in
   * the dashboard for now (see CardDetailDrawer's Links section); editing is
   * not yet wired up client-side. */
  links: { label: string; path: string }[];
  /** The card's stored PR ref/URL (WF-073) — set via `overseer set-field
   * --pr`, plain passthrough from `Card.pr`. NOT the same thing as
   * `Context.pr` (`PrWindow`, below) — that's live census session data
   * about whichever PR the SESSION currently has open, unrelated to any
   * particular card. Always present, but null on cards with no PR set. */
  pr: string | null;
}

/** Project/sprints/quarantined shapes are loose in the backend contract. */
export interface Board {
  project: unknown;
  cards: BoardCard[];
  sprints: unknown[];
  quarantined: unknown[];
  /** F10, WF-067: the editable label-colour registry — `{label: color_key}`.
   * A registry hit wins over `labelColor`'s hash-palette fallback (see
   * `board/labelColor.ts`). Always present (possibly `{}`), same
   * blank-tolerant contract as `labels`/`checklist` on `BoardCard`. */
  label_colors: Record<string, string>;
}

export interface PrWindow {
  number?: number;
  url?: string;
  review_state?: string;
}

/** census-derived extras are optional — may be absent entirely. */
export interface Context {
  pct: number | null;
  threshold: number | null;
  model?: string;
  session_name?: string;
  pr?: PrWindow;
  stale?: boolean;
  /** Census sees the status line still rendering, but the session's activity
   * counters haven't moved for 10 minutes — an open TUI nobody is working in.
   * Distinct from `stale`, which means census sees no render at all. */
  idle?: boolean;
}

export interface RateWindow {
  used_percentage?: number;
  resets_at?: number;
}

export type Limits = {
  five_hour?: RateWindow;
  seven_day?: RateWindow;
} | null;

export interface BoardResponse {
  board: Board;
  context: Context;
  limits: Limits;
}

/** GET /api/card/{id} — full card fields plus body content. */
export interface CardDetail extends BoardCard {
  sections: Record<string, string>;
  body: string;
}

export interface OrderBody {
  order: number;
}

export interface PriorityBody {
  priority: string | null;
}

export interface ParentBody {
  parent: string | null;
}

export interface DependsBody {
  on?: string;
  off?: string;
}

export type MoveBody = { stage: Stage } | { status: Status; reason?: string };

export interface ThresholdBody {
  value: number;
}

export interface ClaimBody {
  session_id: string;
}

/** POST /api/card body — creates a new card. */
export interface CreateCardBody {
  title: string;
  complexity?: string | null;
  labels?: string[];
  goal?: string | null;
}

/** POST /api/card/{id} body — edits an existing card's title/body markdown. */
export interface EditCardBody {
  title?: string;
  body?: string;
}

/** POST /api/card response — the usual board payload plus the new card's id. */
export interface CreateCardResponse extends BoardResponse {
  card_id: string;
}

/** POST /api/card/{id}/labels body (F1, WF-058). */
export interface LabelsBody {
  labels: string[];
}

export interface SessionSummary {
  id: string;
  worktree_cwd: string | null;
  /** Last time the status line RAN for this session. The status line reruns on
   * a timer, so this refreshes even while the session sits idle — never read it
   * as "last active"; use `active_at`. */
  updated_at: number | null | string;
  /** Last time the session's activity counters MOVED (prompt, cost, tokens,
   * cache requests). Absent for entries written by a census predating it. */
  active_at?: number | null | string;
  stale: boolean;
  /** Still rendering, but no activity for 10 minutes (see Context.idle). */
  idle?: boolean;
  session_name?: string;
  model?: string;
  /** Git branch the session's worktree is on (WF-031) — omitted when
   * census/derive_repo_root couldn't resolve one. */
  branch?: string;
  pr?: PrWindow;
  pct?: number;
}

export interface SessionsResponse {
  sessions: SessionSummary[];
}

/** One discoverable board (WF-030 repo selector) — `root` is the MAIN repo
 * root path (stable across worktrees), used verbatim as the `root` query
 * param on every subsequent API call once selected. `current` marks
 * whichever entry matches the dashboard's own launch root.
 *
 * `has_board`/`live_sessions` (WF-032 "unbegun repo" holding page): a repo
 * can be discoverable purely because census sessions are live in it, even
 * though `overseer init` has never been run there — no board.db exists.
 * `has_board: false` marks exactly that case; `live_sessions` is the count
 * of live agents census currently sees under this root, used for the
 * selector's agent-count hint and the holding page's copy. A `has_board:
 * false` root 400s the backend's `/api/board` — callers must never fetch
 * the board for one (see `useBoard`'s `enabled` gate). */
export interface RepoEntry {
  label: string;
  root: string;
  current: boolean;
  has_board: boolean;
  live_sessions: number;
}

export interface ReposResponse {
  repos: RepoEntry[];
}

/** POST /api/repo/clear response — the dashboard's clear-data action
 * (per-repo cards-only or full-repo destructive clear, always preceded by
 * a git-trackable backup). `backup_path` is null on a `noop` clear (nothing
 * existed to remove); `removed` is a loose passthrough of whatever the
 * backend actually deleted, keyed by target name. */
export interface ClearResponse {
  scope: "cards" | "repo";
  backup_path: string | null;
  removed: Record<string, unknown>;
  label: string;
  noop: boolean;
}

// --- Chronicle (optional sibling plugin — session telemetry) ---------------
// Mirrors `plugins/chronicle/scripts/report.py`'s JSON. The dashboard grows
// a Chronicle page only when `/api/chronicle/status` says the plugin is
// installed; every shape below is what chronicle's CLI prints verbatim.

export interface ChronicleStatus {
  installed: boolean;
  exists: boolean;
  db?: string;
  sessions?: number;
  turns?: number;
  repos?: number;
  last_ingest_at?: number | null;
  /** Epoch seconds of the last `sync`, null before the first one. */
  synced_at?: number | null;
}

/** POST /api/chronicle/sync — what the on-demand pull found and did. */
export interface ChronicleSyncResponse {
  /** Transcript files stat-ed (main + subagent files). */
  scanned: number;
  /** Sessions with at least one file that moved since last seen. */
  changed: number;
  /** New JSONL lines parsed across those sessions. */
  lines: number;
  /** Ids of the sessions that changed. */
  sessions: string[];
  synced_at: number;
}

export interface ChronicleTotals {
  sessions: number;
  turns: number;
  prompts: number;
  tool_calls: number;
  input_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  output_tokens: number;
  thinking_tokens: number;
  compactions: number;
  /** Main-agent turns that wrote more cache than they read (first call,
   * TTL lapsed, or prefix changed). */
  cold_turns: number;
  subagents: number;
  active_ms: number;
  transcript_bytes: number;
  live: number;
  /** cache_read / (input + cache_read + cache_creation); null with no context. */
  cache_hit_rate: number | null;
  /** Cache-creation tokens split by TTL. */
  cache_5m_tokens: number;
  cache_1h_tokens: number;
  /** Largest single window reached by any session in the range. */
  peak_context_tokens: number;
  /** That peak as a share of its inferred window (200k or 1M). */
  peak_context_pct: number | null;
  context_window: number;
}

export interface ChronicleDay {
  day: string;
  sessions: number;
  turns: number;
  input_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  output_tokens: number;
  cold_turns: number;
  /** Largest single main-agent context window seen that day. */
  peak_context_tokens: number;
  /** That peak as a share of its inferred window. */
  peak_context_pct: number | null;
  cache_hit_rate: number | null;
}

export interface ChronicleModel {
  model: string;
  turns: number;
  sessions: number;
  input_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  output_tokens: number;
}

export interface ChronicleTool {
  tool_name: string;
  calls: number;
  sessions?: number;
}

export interface ChronicleQuantiles {
  p50: number | null;
  p90: number | null;
  max: number | null;
  mean: number | null;
}

export interface ChronicleShape {
  turns: ChronicleQuantiles;
  prompts: ChronicleQuantiles;
  duration_s: ChronicleQuantiles;
  transcript_bytes: ChronicleQuantiles;
  peak_context_tokens: ChronicleQuantiles;
}

export interface ChronicleSummary {
  /** `null` when chronicle has no store yet (or the plugin is absent). */
  totals: ChronicleTotals | null;
  by_day?: ChronicleDay[];
  by_model?: ChronicleModel[];
  tools?: ChronicleTool[];
  shape?: ChronicleShape;
}

export interface ChronicleSession {
  session_id: string;
  project_slug: string | null;
  cwd: string | null;
  repo_root: string | null;
  git_branch: string | null;
  entrypoint: string | null;
  version: string | null;
  title: string | null;
  transcript_path: string | null;
  transcript_bytes: number;
  started_at: number | null;
  ended_at: number | null;
  end_reason: string | null;
  last_activity_at: number | null;
  updated_at: number;
  turns: number;
  prompts: number;
  tool_calls: number;
  input_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  output_tokens: number;
  thinking_tokens: number;
  peak_context_tokens: number;
  compactions: number;
  cold_turns: number;
  subagents: number;
  active_ms: number;
  models: string[];
  cache_hit_rate: number | null;
  /** Peak context as a share of the window inferred for this session. */
  peak_context_pct: number | null;
  context_window: number;
  /** Derived server-side: last activity minus start, in seconds. */
  duration_s: number | null;
  /** Derived: input + cache read + cache creation, summed over turns. */
  context_tokens: number;
  live: boolean;
}

export interface ChronicleSessionsResponse {
  sessions: ChronicleSession[];
}

export interface ChronicleTurn {
  ts: number | null;
  model: string | null;
  context_tokens: number;
  input_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  cache_5m_tokens: number;
  cache_1h_tokens: number;
  output_tokens: number;
  thinking_tokens: number;
  tool_calls: number;
  stop_reason: string | null;
  /** cache_creation > cache_read for this call. */
  cold: boolean;
  /** Seconds since the previous main-agent call; null for the first. */
  gap_s: number | null;
}

export interface ChronicleSubagent {
  agent_id: string;
  turns: number;
  context_tokens: number;
  output_tokens: number;
  tool_calls: number;
  first_ts: number | null;
  last_ts: number | null;
}

/** `GET /api/chronicle/session/{id}` — the session row plus its per-turn
 * series. NOTE: `subagents` here is the per-agent LIST, not the rollup
 * count `ChronicleSession.subagents` carries (chronicle's CLI replaces the
 * count with the breakdown on the detail verb). */
export interface ChronicleSessionDetail extends Omit<ChronicleSession, "subagents"> {
  turn_series: ChronicleTurn[];
  subagents: ChronicleSubagent[];
  tools: ChronicleTool[];
  compactions_at: number[];
}

/** Query knobs shared by the summary and sessions reads. */
export interface ChronicleQuery {
  /** Only sessions active in the last N days; omit for all time. */
  days?: number;
  /** `"all"` drops the repo filter (account-wide); default scopes to the
   * active root exactly like `/api/board`. */
  scope?: "repo" | "all";
}
