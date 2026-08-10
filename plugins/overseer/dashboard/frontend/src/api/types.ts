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
}

/** Project/sprints/quarantined shapes are loose in the backend contract. */
export interface Board {
  project: unknown;
  cards: BoardCard[];
  sprints: unknown[];
  quarantined: unknown[];
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
  updated_at: number | null | string;
  stale: boolean;
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
