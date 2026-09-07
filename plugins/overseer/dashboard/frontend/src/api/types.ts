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

/** POST /api/card/{id}/attributes (WF-070) — only the keys PRESENT are
 * changed; `null` clears one. */
export interface AttributesBody {
  complexity?: string | null;
  sprint?: string | null;
  estimate?: number | null;
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
  /** Census sees the status line still rendering, but the session's activity
   * counters haven't moved for 10 minutes — an open TUI nobody is working in.
   * Distinct from `stale`, which means census sees no render at all.
   *
   * Check `stale` FIRST: a session that died within ten minutes of its last
   * activity is `idle: false`, so read alone this field says "working". */
  idle?: boolean;
  /** Multi-account: the Claude config dir whose census store reported this
   * session (e.g. "/Users/x/.claude-personal"). Absent on a single store. */
  config_dir?: string;
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
  /** Whether chronicle has sessions for this root — i.e. whether the Chronicle
   * page may be SCOPED to it. Independent of `has_board`: a repo Claude Code
   * ran in but no board was ever raised for is `has_board: false` and
   * `chronicled: true`, and before WF-108 was unreachable from the selector
   * despite being the largest repo in the store.
   *
   * Optional: a frontend talking to a backend from before WF-108 gets nothing
   * here, and callers fall back to `has_board` — exactly the old behaviour. */
  chronicled?: boolean;
  /** Epoch seconds of the repo's most recent session activity, from census
   * (live/recent) and chronicle (history) — whichever is newer. Null when
   * neither knows the repo. The list arrives sorted by it, newest first. */
  last_active_at?: number | null;
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
  /** Distinct artifact pages published (republishes of one url count once). */
  artifacts: number;
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
  /** API-equivalent cost in USD at Anthropic list prices (see chronicle's
   * pricing.py) — a yardstick, not a bill. Turns on a model the table does
   * not know contribute nothing and are counted in `unpriced_turns`. */
  cost_usd: number;
  unpriced_turns: number;
  /** ISO date the pricing table was last checked. */
  pricing_as_of: string;
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
  cost_usd: number;
  unpriced_turns: number;
}

export interface ChronicleModel {
  model: string;
  turns: number;
  sessions: number;
  input_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  cache_5m_tokens: number;
  cache_1h_tokens: number;
  output_tokens: number;
  /** Null when the model is not in the pricing table. */
  cost_usd: number | null;
}

/** Measures every usage bucket carries, so the callout's three tabs are
 * directly comparable. `median_s` is null when no call in the bucket had both
 * a start and a result timestamp. */
export interface ChronicleUsage {
  calls: number;
  /** Characters the tool's results poured back into the context. */
  result_chars: number;
  /** Wall time of the MIDDLE call — never the mean, which one overnight
   * `AskUserQuestion` would drag somewhere no call ever was. */
  median_s: number | null;
  /** How many of these calls came from a subagent rather than the main loop. */
  subagent_calls: number;
  /** Absent on a single-session read, where it would always be 1. */
  sessions?: number;
}

export interface ChronicleTool extends ChronicleUsage {
  tool_name: string;
}

export interface ChronicleMcpServer extends ChronicleUsage {
  /** The slug the tool name carries (`claude_ai_Snowflake`). The key
   * everything joins on, and the label of last resort. */
  server: string;
  /** The server's real name as attribution records it — `claude.ai
   * Snowflake` for that slug. Falls back to the slug server-side, and is
   * absent altogether from a backend that predates the join. */
  name?: string;
  /** "plugin" | "connector" | "local" — where the server comes from. */
  provenance: string;
  /** How many distinct tools of that server were called. */
  tools: number;
}

export interface ChronicleMcpTool extends ChronicleUsage {
  server: string;
  name?: string;
  tool: string;
}

export interface ChronicleMcp {
  calls: number;
  result_chars: number;
  by_provenance: Record<string, number>;
  servers: ChronicleMcpServer[];
  tools: ChronicleMcpTool[];
  sessions?: number;
}

export interface ChroniclePluginItem extends ChronicleUsage {
  plugin: string;
  /** "mcp" | "skill" — how this plugin was used. */
  kind: string;
}

export interface ChronicleFileChurn {
  file_path: string;
  edits: number;
  lines_added: number;
  lines_removed: number;
  /** "edit" | "create" | "update", deduplicated. */
  operations: string[];
  sessions: number;
}

/** Editing DONE, not lines surviving in the repo: ten edits to one line are
 * ten edits, and a later revert still counts. For "what shipped", git is the
 * truthful source. */
/** One thing that was in scope, with the turns and tokens spent under it.
 * Attribution rides on TURNS, so these are token and cost figures — not
 * invocation counts. `plugin` is null for a built-in skill. */
export interface ChronicleAttributed {
  name: string;
  turns: number;
  context_tokens: number;
  output_tokens: number;
  sessions: number;
  cost_usd: number | null;
  unpriced_turns?: number;
  /** Skills tab only: the plugin supplying it, null for a built-in. */
  plugin?: string | null;
  /** Plugins tab only: how many distinct skills of that plugin ran. */
  skills?: number;
}

export interface ChronicleAttribution {
  turns: number;
  /** Cost of turns with anything in scope, counted ONCE — a plugin skill
   * inside a subagent sets both fields, so summing the lists double-bills. */
  cost_usd: number;
  unattributed_cost_usd: number;
  /** Turns with anything in scope — the honest denominator. Most turns have
   * nothing, correctly. */
  attributed_turns: number;
  plugins: ChronicleAttributed[];
  skills: ChronicleAttributed[];
  agents: ChronicleAttributed[];
  mcp: ChronicleAttributed[];
}

export interface ChronicleChurnDay {
  day: string;
  lines_added: number;
  lines_removed: number;
  edits: number;
}

export interface ChronicleChurn {
  lines_added: number;
  lines_removed: number;
  files: number;
  edits: number;
  files_by_churn: ChronicleFileChurn[];
  /** Sessions that actually changed a file — the only honest denominator for
   * a per-session average, since a session that edited nothing would
   * otherwise drag every such figure down. */
  sessions: number;
  /** Output tokens over those same sessions, so output-per-line compares
   * two numbers drawn from the same set. */
  output_tokens: number;
  by_day: ChronicleChurnDay[];
}

/** What subagents DO against what they PRODUCE. Counted from `agent_id`,
 * which every turn and tool call carries — so unlike attribution this covers
 * the whole store. Raw pairs, not percentages: the caller renders them. */
export interface ChronicleDelegation {
  turns: number;
  subagent_turns: number;
  output_tokens: number;
  subagent_output_tokens: number;
  tool_calls: number;
  subagent_tool_calls: number;
}

export interface ChroniclePlugins {
  calls: number;
  items: ChroniclePluginItem[];
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
  cost_usd: ChronicleQuantiles;
}

/** One published artifact PAGE — the latest publish of a url, with how many
 * times it was published in that session and when it first appeared. */
export interface ChronicleArtifact {
  session_id: string;
  session_title?: string | null;
  /** Latest publish time. */
  ts: number | null;
  first_ts: number | null;
  /** Null when the publish's result never landed in the transcript. */
  url: string | null;
  title: string | null;
  description: string | null;
  favicon: string | null;
  publishes: number;
}

/** One entry in a session's biggest-jumps list: the turn whose context grew
 * most since the previous one, attributed to what landed in between. */
export interface ChronicleJump {
  turn: number;
  ts: number | null;
  context_tokens: number;
  delta_tokens: number;
  output_tokens: number;
  cold: boolean;
  tool_calls: number;
  /** Top three tool results (by size) that landed before this turn. */
  landed: { tool_name: string; chars: number }[];
  /** Every result that landed before this turn, in characters. */
  landed_chars: number;
}

export interface ChronicleSummary {
  /** `null` when chronicle has no store yet (or the plugin is absent). */
  totals: ChronicleTotals | null;
  by_day?: ChronicleDay[];
  by_model?: ChronicleModel[];
  tools?: ChronicleTool[];
  mcp?: ChronicleMcp;
  plugins?: ChroniclePlugins;
  churn?: ChronicleChurn;
  attribution?: ChronicleAttribution;
  delegation?: ChronicleDelegation;
  shape?: ChronicleShape;
  artifacts?: ChronicleArtifact[];
}

export interface ChronicleSession {
  session_id: string;
  project_slug: string | null;
  cwd: string | null;
  repo_root: string | null;
  git_branch: string | null;
  /** Multi-account: the Claude config dir the transcript was read from.
   * Absent/null on rows ingested before the column existed. */
  config_dir?: string | null;
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
  artifacts: number;
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
  /** API-equivalent cost at list prices, every agent's turns included. */
  cost_usd: number;
  unpriced_turns: number;
  /** Editing done in this session, from the diffs in its transcript. Zero
   * on a session whose transcript was pruned before ingest as well as on one
   * that genuinely edited nothing — the two are indistinguishable here, so
   * the table renders zero as "—" rather than as a claim of no work. */
  lines_added: number;
  lines_removed: number;
  files_touched: number;
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
  /** This call at list prices; null when its model is unpriced. */
  cost_usd: number | null;
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
 * count with the breakdown on the detail verb); likewise `artifacts` is the
 * page LIST here and the distinct-page count on the session row. */
export interface ChronicleSessionDetail extends Omit<ChronicleSession, "subagents" | "artifacts"> {
  turn_series: ChronicleTurn[];
  subagents: ChronicleSubagent[];
  tools: ChronicleTool[];
  mcp?: ChronicleMcp;
  plugins?: ChroniclePlugins;
  churn?: ChronicleChurn;
  /** The window-level blocks, narrowed to this session. Optional: a store
   * that predates the attribution columns returns neither. */
  attribution?: ChronicleAttribution;
  delegation?: ChronicleDelegation;
  compactions_at: number[];
  artifacts: ChronicleArtifact[];
  biggest_jumps: ChronicleJump[];
}

/** Query knobs shared by the summary and sessions reads. */
export interface ChronicleQuery {
  /** Only sessions active in the last N days; omit for all time. */
  days?: number;
  /** `"all"` drops the repo filter (account-wide); default scopes to the
   * active root exactly like `/api/board`. */
  scope?: "repo" | "all";
  /** Only sessions chronicle last saw on this git branch (session-level: a
   * session that switched branches counts wholly where it ended up). */
  branch?: string | null;
}
