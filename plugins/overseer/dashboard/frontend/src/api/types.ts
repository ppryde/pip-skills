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

/** One account the selector can scope to (WF-116) — the union of every
 * account uuid chronicle has recorded a session under and every watched
 * Claude config dir's CURRENT login. `plan`/`config_dirs` come only from a
 * live login: a uuid chronicle knows but no dir is currently logged into
 * has `plan: null` and `config_dirs: []`, and is still selectable. No
 * email or name ever appears — the backend reads a whitelist only. */
export interface AccountEntry {
  account_uuid: string;
  /** First 8 characters of `account_uuid`, for a compact selector label. */
  short_uuid: string;
  /** Raw plan value (e.g. "claude_max") — render through `planLabel`
   * (board/chronicle/plan.ts), never shown raw. */
  plan: string | null;
  /** Every watched config dir currently logged into this account — used to
   * scope live census sessions (`/api/sessions?account=`) to it. */
  config_dirs: string[];
  /** Sessions chronicle has recorded under this uuid. */
  sessions: number;
  last_activity_at: number | null;
}

export interface AccountsResponse {
  accounts: AccountEntry[];
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
  /** Docker volumes read in place, one entry per volume that synced. Absent on an older chronicle. */
  volumes?: { name: string; scanned: number; changed: number; lines: number; partial?: boolean }[];
  /** A configured volume that could not be read (docker down, volume missing, timeout); local dirs
   *  still synced. `volume` is null for a config entry skipped as invalid. */
  volume_errors?: { volume: string | null; error: string }[];
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
  /** Mean main-agent context size that day (subagent turns excluded). */
  avg_context_tokens: number;
  /** That average as a share of the SAME window the day's peak infers. */
  avg_context_pct: number | null;
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

/** One tool's contribution to context growth. `share` is of CHARACTERS
 * RETURNED, never of dollars — see `ChronicleContextGrowth`. */
export interface ChronicleContextTool {
  tool_name: string;
  /** Every call in the window. */
  calls: number;
  /** Only those that recorded a result size — the denominator for
   * `avg_chars`, since a call still in flight has none. */
  measured_calls: number;
  result_chars: number;
  /** Fraction of everything returned in the window, 0..1. */
  share: number;
  /** Typical result size. Null where nothing was measured: "we don't know"
   * and "it returned nothing" are different claims. */
  avg_chars: number | null;
}

/** What GREW the context, per tool.
 *
 * Deliberately NOT cost by tool. A turn's cost is the prompt it carried, paid
 * before any of its tools ran — a turn that called five tools did not pay
 * five times, so splitting its dollars across them would be invention. The
 * other direction holds: a tool RESULT is text that enters the context, and
 * every turn after it carries that text again.
 *
 * Shares are of characters for the same reason a dollar figure is refused: a
 * result re-sent at cache-read rates costs a fraction of one at creation
 * rates, and a compaction drops some of it outright. */
export interface ChronicleContextGrowth {
  /** Everything returned in the window, across all tools — including any
   * beyond the truncated `tools` list, so a share is honest. */
  result_chars: number;
  calls: number;
  measured_calls: number;
  /** Distinct tools in the window, so a truncated list can say what it is a
   * truncation of. */
  tools_total: number;
  tools: ChronicleContextTool[];
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

export interface ChronicleMcpServer {
  server: string;
  /** "plugin" | "connector" | "local" — where the server comes from. */
  provenance: string;
  tools: number;
  calls: number;
  result_chars: number;
  /** Absent on a single-session read, where it would always be 1. */
  sessions?: number;
}

export interface ChronicleMcpTool {
  server: string;
  tool: string;
  calls: number;
  result_chars: number;
  sessions?: number;
}

export interface ChronicleMcp {
  calls: number;
  result_chars: number;
  by_provenance: Record<string, number>;
  servers: ChronicleMcpServer[];
  tools: ChronicleMcpTool[];
  sessions?: number;
}

export interface ChroniclePluginItem {
  plugin: string;
  /** "mcp" | "skill" — how this plugin was used. */
  kind: string;
  calls: number;
  sessions?: number;
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

/** A usage-limit kind, as `chronicle limits` classifies the banner Claude
 * Code writes into the transcript. `"other"` is an unrecognised wording —
 * kept, never dropped, so a future banner change still shows up. */
export type ChronicleLimitKind = "session" | "weekly" | "monthly_spend" | "model" | "other";

/** Token usage (and cost) an account burned reaching one deduped limit event,
 * summed across all its sessions and subagents from the window's inferred
 * start to the moment it was hit. `null` on the event itself when the window
 * can't be inferred (see `ChronicleLimitKind` — only "session" and "weekly"
 * have a documented window) or there's no account to sum against. */
export interface ChronicleLimitTokens {
  input_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost_usd: number;
  unpriced_turns: number;
  /** Epoch seconds: `resets_at` minus the limit's fixed period. */
  window_start: number;
}

/** One deduplicated real-world limit hit — Claude Code writes the SAME hit
 * into every session and subagent running at the time, folded here into one
 * event per (account, kind, model), clustering rows that landed close
 * together in time (so a hit logged with a reset in one session and without
 * in another still merges). */
export interface ChronicleLimitEvent {
  account_uuid: string | null;
  kind: ChronicleLimitKind;
  /** The model named in a "reached your <model> limit" banner; null for
   * every other kind. */
  model: string | null;
  /** Epoch seconds of the earliest session to log this event. */
  hit_at: number | null;
  /** Epoch seconds of the latest session to log this event (useful when a
   * session kept retrying across a long-open window). */
  last_seen_at: number | null;
  /** Epoch seconds this resets — the banner's own stated time when it
   * parsed, otherwise DERIVED (a session limit's window close, or a weekly
   * limit's anchor) — see `resets_at_inferred`. */
  resets_at: number | null;
  /** True when `resets_at` was derived rather than read off the banner
   * itself (its text carried no reset, or none parsed) — an honest label
   * for a value this call computed, not one Claude Code stated. */
  resets_at_inferred: boolean;
  /** The reset clause verbatim ("11:50am (Europe/London)"), before parsing;
   * null when the banner stated none (whether or not `resets_at` was later
   * inferred). */
  reset_raw: string | null;
  /** How many distinct sessions logged this same event. */
  sessions: number;
  tokens_to_limit: ChronicleLimitTokens | null;
}

export interface ChronicleLimitsResponse {
  events: ChronicleLimitEvent[];
  by_kind: Partial<Record<ChronicleLimitKind, number>>;
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
  /** Optional: a store that predates `result_chars` returns none. */
  context_growth?: ChronicleContextGrowth;
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
  /** The plan this session RAN ON, snapshotted at ingest — `claude_max`,
   * `claude_enterprise`, … Absent/null when unknown (no account file, or an
   * API-key config, which has no oauthAccount at all). Consumers render
   * nothing rather than guessing: null means "not stated", not "no plan". */
  plan_organization_type?: string | null;
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
  /** What the agent was handed, lifted verbatim from the first prompt of its
   * own transcript and truncated. The only legible name an agent has — its
   * id is a hash. Null for an agent whose opening prompt was pruned, or in a
   * store not yet resynced with `chronicle sync --full`.
   *
   * UNTRUSTED transcript text: render as a text node, never as markup. */
  task: string | null;
  /** "Explore", "general-purpose", … as attribution records it. */
  agent_type: string | null;
  /** The agent's SHORT label, from `agent-<id>.meta.json` — a purpose-built
   * three-to-five word summary. Prefer this over `task`, which is the opening
   * prompt and runs to thousands of characters. Null on the handful of agents
   * with no meta file, and in a store not yet resynced with `--full`. */
  description?: string | null;
  /** API-equivalent cost of this agent's turns at list prices. Absent from a
   * backend that predates the join; null is never sent — an agent whose model
   * the pricing table does not know reports 0 here and says so through
   * `unpriced_turns` instead, so "free" and "unknown" stay distinguishable. */
  cost_usd?: number;
  /** Turns on a model with no published price. Nonzero means `cost_usd` is a
   * floor, not a total. */
  unpriced_turns?: number;
}

/** `GET /api/chronicle/session/{sid}/agent/{aid}` — one subagent in detail.
 * The same shape the session drawer reads, narrowed to one agent: its own
 * turns, tool calls, edits and cost. */
export interface ChronicleAgentDetail {
  session_id: string;
  agent_id: string;
  task: string | null;
  agent_type: string | null;
  turns: number;
  context_tokens: number;
  input_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  output_tokens: number;
  thinking_tokens: number;
  tool_calls: number;
  peak_context_tokens: number;
  first_ts: number | null;
  last_ts: number | null;
  duration_s: number | null;
  cache_hit_rate: number | null;
  cost_usd: number;
  unpriced_turns: number;
  turn_series: ChronicleTurn[];
  tools: ChronicleTool[];
  mcp?: ChronicleMcp;
  plugins?: ChroniclePlugins;
  churn?: ChronicleChurn;
  context_growth?: ChronicleContextGrowth;
  artifacts: ChronicleArtifact[];
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
  context_growth?: ChronicleContextGrowth;
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
  /** Only sessions active in the last N days; omit for all time. Mutually
   * exclusive with `since` — `since` wins if both are somehow set (see
   * `chronicleQuery` in api/client.ts). */
  days?: number;
  /** The exact-instant sibling of `days` — `"today"` (local midnight) or
   * `"month-to-date"` (local midnight on the 1st), both carrying THIS
   * browser's own UTC offset and resolved to an ISO datetime at request
   * time, so a poll tick that lands after a day/month boundary always names
   * the new one rather than a value computed when the filter was chosen. */
  since?: "today" | "month-to-date";
  /** `"all"` drops the repo filter (account-wide); default scopes to the
   * active root exactly like `/api/board`. */
  scope?: "repo" | "all";
  /** Only sessions chronicle last saw on this git branch (session-level: a
   * session that switched branches counts wholly where it ended up). */
  branch?: string | null;
}

// ---------------------------------------------------------------------------
// Almoner — the optional inflow-triage plugin (mail / Linear / Slack).
//
// Shaped like the chronicle types above because the plugin is optional in the
// same way: `installed: false` is a normal answer, not an error, and every
// read degrades to an empty digest rather than failing the page.
// ---------------------------------------------------------------------------

/** What a source is asking of you. `null` until the judging pass runs — the
 * CLI alone fetches and filters, and a digest with no skill behind it is
 * unranked but still usable (that is the boundary test). `"reconcile"` is
 * the odd one out: nobody sent it, it is derived by joining two sources. */
export type AlmonerAsks =
  | "review" | "reply" | "rsvp" | "acknowledge" | "verify" | "reconcile" | "fyi";

/** One message inside a collapsed conversation, for the expanded view.
 *
 * These ride INLINE in the digest rather than being fetched when a row is
 * opened: at real volumes the payload is trivial, and a per-expand fetch
 * would mean a fresh headless agent run every time you opened a row.
 *
 * They ARE persisted. The original design cached nothing a source said; that
 * non-goal was dropped deliberately (see the 2026-09-13 design doc) so the
 * page can render instantly from the last gather and history can be browsed.
 * The consequence is that stored content may diverge from the source — a
 * historical row is a snapshot stamped with when it was gathered, never a
 * live view. */
export interface AlmonerMessage {
  who?: string;
  text: string;
  /** ISO 8601. */
  at?: string;
  /** Permalink to this individual message in the source app. */
  url?: string;
}

/** One row of the digest: a CONVERSATION, never a single message.
 *
 * The conversation grain is the finding that Slack forced — a run of five
 * messages from one person inside a minute is one thing to deal with, and
 * five rows of it is noise you would have to re-triage by hand. */
export interface AlmonerItem {
  /** Stable across refreshes and across transports; used for dedup. Shaped
   * `<source>:<conversation>` so the same event seen twice collapses. */
  id: string;
  source: string;
  context: string;
  /** Who and where — "Group DM · Rhona, Tomas", not the last message's text. */
  title: string;
  /** The newest inbound message — what the triage decision is made on. */
  excerpt?: string;
  /** How many messages collapsed into this row. */
  count?: number;
  /** The collapsed messages, oldest first — what the row expands to show.
   * Absent for sources with no message grain (a Linear notification, a
   * derived reconcile item), which therefore do not expand. */
  messages?: AlmonerMessage[];
  who?: string;
  /** ISO 8601. Absent on derived items (`asks: "reconcile"`), which nobody sent. */
  arrived?: string;
  due?: string | null;
  /** A ROLLUP of several machine-written arrivals of one kind — "3 delivery
   * updates", "4 newsletters" — rather than a conversation.
   *
   * A real mailbox scan found eighteen of twenty threads were machine-written.
   * Dropping them silently loses information ("did my parcel ship?"); listing
   * them individually drowns the two that a person wrote. Folding each
   * category into one collapsed row keeps both: the day stays readable, and
   * nothing has actually gone. `messages` carries the individual items, so it
   * expands with exactly the same control as a conversation.
   *
   * REQUIREMENT on a bundled row: its `excerpt` must name the SUBJECTS, not
   * restate the count. "3 security alerts" over "3 security alerts" is a row
   * you must open every time, which defeats the fold; "mail account: new
   * sign-in, and an app granted access · photo service: login code" can be
   * dismissed at a glance. Which account, which order, which parcel — the
   * adapter is expected to extract that, and a rollup that cannot is better
   * left as individual rows.
   *
   * SAFETY RULE: never fold a security or access event the almoner cannot
   * positively attribute to the reader. A sign-in you made is noise; a
   * sign-in you did not make, to a bank, is the most urgent thing that can
   * arrive all week, and burying it under "3 security alerts" beside the
   * newsletters is worse than not folding at all. When attribution is
   * uncertain the item escapes the bundle as its own row, `awaiting: true`.
   * The same caution applies to anything naming money, credentials or a
   * password reset. Folding is an optimisation; this is the case where the
   * optimisation is not worth its cost. */
  bundled?: boolean;
  /** MECHANICAL, computed by the CLI, identical across transports: the last
   * message in the conversation is not yours. The single cheapest signal we
   * have, and deliberately not a judgement — the skill never sets it. */
  awaiting?: boolean;
  asks?: AlmonerAsks | null;
  /** Deep link to the conversation in the source app — the Slack permalink,
   * the Linear issue. The page's whole job is triage, so acting on a row
   * means leaving for the app that owns it. */
  url?: string;
  /** Every source this was found in — these systems email you, so one event
   * legitimately arrives twice. */
  seen_in?: string[];
  /** Filled by the judging pass; null when it did not run. */
  rank?: number | null;
  because?: string | null;
}

/** One configured source and whether this refresh reached it. A source that
 * fails degrades to `ok: false` and is NAMED in the UI — a silently short
 * digest is worse than an error. */
export interface AlmonerSource {
  label: string;
  type: string;
  ok: boolean;
  /** How the source was reached: `"agent"` (connector-backed, headless) or
   * `"api"` (direct token). The swap seam — a config edit, not a refactor. */
  via?: string;
  watermark?: number | null;
  error?: string;
}

/** GET /api/almoner/status */
export interface AlmonerStatus {
  installed: boolean;
  /** False when the plugin is present but no sources are configured — which
   * renders "not configured", exactly as chronicle renders "not installed". */
  configured?: boolean;
  sources?: AlmonerSource[];
}

/** GET /api/almoner/digest */
export interface AlmonerDigest {
  items: AlmonerItem[];
  sources?: AlmonerSource[];
  /** Epoch seconds this digest was assembled. */
  fetched_at?: number | null;
  /** True when the judging pass ran; false means `rank` is null throughout
   * and the page falls back to its own deterministic order. */
  ranked?: boolean;
  /** How many candidates the pre-filter discarded before ranking.
   *
   * Load-bearing, not a curiosity. A scan of a real mailbox found two human
   * messages in twenty threads — so a digest of two rows that does not say it
   * dropped eighteen reads as a quiet inbox rather than as filtering that
   * worked. It is also the number that makes the `suppressed` audit table
   * worth opening: a triage filter you cannot see is one you cannot trust. */
  suppressed?: number;
  /** Set only when the almoner CLI itself failed — timed out, exited
   * non-zero, or answered bad JSON — while `items`/`sources` still come back
   * as empty arrays so old clients degrade gracefully. Distinguishes that
   * failure from a genuinely empty digest, which carries no `error` at all:
   * without this, both shapes are byte-identical and a real failure renders
   * as the silently-short "nothing needs you" empty state the design
   * forbids. The page treats its presence as a fetch error, same as a
   * network failure. */
  error?: string;
}
