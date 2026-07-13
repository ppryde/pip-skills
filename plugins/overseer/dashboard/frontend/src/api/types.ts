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

export type Priority = "P0" | "P1" | "P2" | "P3";

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
  /** Always present (possibly []) — see checklistWindow.ts's ChecklistEntry
   * doc comment for the backend's string-coercion / status quirks. */
  checklist: ChecklistEntry[];
  /** Top-level repo name the card originated from (never the worktree
   * directory name) — absent on cards minted before this label existed. */
  repo?: string;
  /** Claim fields (design spec §5) — census `session_id` holding the card,
   * ISO-minute stamp, and whether a work verb has acked the claim since.
   * Absent/null on never-claimed cards; board/card-detail JSON passthrough,
   * no new backend model work. */
  claimed_by?: string | null;
  claimed_at?: string | null;
  claim_acked?: boolean;
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

export interface SessionSummary {
  id: string;
  worktree_cwd: string | null;
  updated_at: number | null | string;
  stale: boolean;
  session_name?: string;
  model?: string;
  pr?: PrWindow;
  pct?: number;
}

export interface SessionsResponse {
  sessions: SessionSummary[];
}
