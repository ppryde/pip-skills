# Chronicle — session telemetry for the overseer dashboard

**Date:** 2026-09-04
**Status:** Implemented (v0.1.0, PR pending)
**Topic:** Record every Claude Code session's token usage, size and shape into a
queryable store, and show it on a new dashboard page when the plugin is present.

---

## 1. Problem & context

Claude Code writes a complete transcript per session
(`~/.claude/projects/<slug>/<session>.jsonl`), and every assistant record in it
carries the API `usage` block — exact per-call input, cache read, cache
creation, output and thinking token counts, plus the model. Nothing collects
those across sessions. Census captures the status line (live context %, rate
limits) but only for sessions that are alive; the transcript is the only record
of what a finished session cost.

The user's goal: **analyse token usage, session sizes and lengths in detail**,
as a plugin that hooks into the overseer dashboard and adds a page when it is
installed.

## 2. Decisions

### Source of truth: the transcript, not hook payloads
Hook payloads carry ids and paths, not usage. The transcript has everything and
is append-only, so an ingest can be incremental by byte offset. Subagent
transcripts (`<session>/subagents/agent-*.jsonl`) have the same shape and are
folded into the parent session, tagged by agent.

One API call is written as several JSONL lines (one per content block) sharing
`message.id` and the same `usage`. Turns are keyed by message id; a naive sum
over lines double- or triple-counts every call. `<synthetic>` assistant records
(locally generated stand-ins) are not API calls and are skipped.

### Pull on demand (MVP), hooks optional
The user asked for the MVP to be pull-based: list the sessions the store knows,
compare with what is on disk, ingest whatever moved, record the latest update,
driven from the UI. So:

- `cursors` records, per transcript file, the byte offset after the last
  complete line **and the file's mtime/size as last seen**.
- `chronicle sync` stats every transcript (main + subagent files), ingests only
  files whose mtime/size differ from the cursor, parses only the bytes appended
  since the offset, rolls the touched sessions up, and writes `synced_at`.
- The dashboard's **Sync** button calls `POST /api/chronicle/sync` (token-gated
  like a mutation; account-wide since the projects dir is not per-repo).

Fail-safe `SessionStart`/`Stop`/`SessionEnd` hooks ship too and run the same
incremental ingest (giving a true end time and reason), but nothing depends on
them. A file watcher was considered and deferred: sync is a directory walk plus
tail reads, cheap enough to run on every page visit.

### Store: SQLite, account-scoped
`$CLAUDE_CONFIG_DIR/chronicle/sessions.db` (override `CHRONICLE_DB`), WAL mode,
busy timeout, additive migrations on open. Rooted at the config dir because
that is Claude Code's account boundary (same reasoning as census). One store
for all repos, with `repo_root` on each session (worktrees resolve to their
main checkout via the git common dir) so the dashboard can scope to the active
repo or the whole account.

Alternatives weighed: a graph database (the data has no relationships a graph
query expresses better; it would need a daemon the hooks could not assume) and
DuckDB (fast columnar analytics, but single-writer — dozens of short-lived hook
processes write concurrently — and a non-stdlib dependency). Volume is a few
thousand turns per account; SQLite is the right size.

### Idempotence by construction
Every fact table is keyed by a transcript-native id (message id, tool_use id,
record uuid — scoped by session) and written with `INSERT OR IGNORE/REPLACE`.
The `sessions` rollup (token totals, turn/prompt/tool counts, peak context,
compactions, subagent count, active time, models) is **recomputed** from the
fact tables after every ingest, never incremented. A file re-read from byte 0
converges on the same rows.

### Dashboard integration: a soft sibling dependency
The backend already reads census through a subprocess client that degrades to
`None`; chronicle follows the same shape (`run_chronicle`,
`chronicle_installed`). Routes: `GET /api/chronicle/{status,summary,sessions,
session/{id}}` (reads take the same validated `root` as `/api/board`, or
`scope=all`) and `POST /api/chronicle/sync`. When the plugin is absent every
read returns an "unavailable" shape and the frontend never renders the entry.

Frontend: a third view (`"chronicle"`) beside Board|Atlas. The two-coin toggle
was documented as reading for exactly two views, so Chronicle gets its own
pressed button next to the coins; while it shows, the Board coin stays in
front (the page a coin click returns to). Charts are hand-rolled SVG (the
dashboard has no charting dependency): one validated hue on the parchment
panel, hairline solid gridlines, ink-token text, hover tooltips that never gate
a value, and a table-view twin under every plot.

## 3. What the page shows

Filter row (window: 7/30/90 days/all; scope: this repo/all repos; Sync), stat
tiles (sessions + live, turns + prompts, tool calls, context processed, output
+ thinking, active time, transcript bytes, subagents + compactions),
context-per-day and output-per-day columns, turns by model, tool leaderboard,
session-shape quantiles (turns, prompts, span, peak context, size at p50/p90/
max), and a sortable session table whose rows open a drawer: identity facts,
tiles, context-per-turn line with compaction hairlines, tools, subagents.

## 4. Measured

On the author's machine: 51 sessions / 181 transcript files / ~80k lines
backfilled in under two seconds; a no-change sync in ~0.1 s; a sync with one
live session appending in ~0.2 s.

## 5. Open questions (deferred)

- **Cost.** ~~Tokens only for now; an estimated-cost column needs a per-model
  pricing table that drifts.~~ Resolved 2026-09-04: `scripts/pricing.py` holds
  the list-price table (dated by `PRICING_AS_OF`); cost is computed at read
  time so the table can drift without a re-sync, and unknown models are
  counted as unpriced rather than guessed.
- **Headline time.** Wall-clock span can be days for resumed sessions; active
  time (summed `turn_duration` markers) is only present where Claude Code
  wrote them. Both are shown; neither is promoted.
- **Retention.** Nothing is pruned.
- **Liveness.** No-end sessions count as live only within 15 minutes of
  activity; census could give a truer answer if the plugins are linked.
