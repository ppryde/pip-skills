---
name: chronicle
description: >
  Session telemetry from Claude Code transcripts: token usage per API call (input, cache
  read/creation, output, thinking), context growth, prompts, tool calls, subagents,
  compactions and duration, folded into an account-scoped SQLite store and shown on the
  overseer dashboard's Chronicle page. Use when the user asks how many tokens a session or
  repo used, "how big are my sessions", "which tools do I call most", "sync the chronicle",
  "backfill session history", or wants session cost/size/length analysed.
---

# Chronicle

The chronicle is a SQLite record of every session's toil, read from the transcripts Claude
Code already writes. Drive it through the CLI (locate `cli.py` relative to this skill; when
installed as a plugin the scripts live under the plugin root). Every verb prints JSON.

```bash
python .../scripts/cli.py <verb>
```

## Sync first
The store only knows what has been synced. Run `sync` before answering any question about
usage — it stats every transcript on disk and ingests only the files that moved, so it is
cheap to run every time. `backfill` is the same verb for a first run.

## Answering questions
- **Totals for a window / repo:** `summary --days N [--root <main repo root>]` — totals,
  per-day series, by-model breakdown, tool leaderboard, and session-shape quantiles
  (turns, prompts, span, peak context, transcript size at p50 / p90 / max).
- **Which sessions:** `sessions --days N [--root R] [--limit N]` — most recent first, each
  with turns, prompts, tool calls, token totals, peak context, subagents, compactions, span.
- **One session in depth:** `session <id>` — the per-turn context series (spot the growth
  curve and where compactions landed), tools used, and per-subagent totals.
- **Store health:** `status` — path, row counts, last sync.

Report numbers as the CLI gives them; say which window and scope you used. "Context
processed" is input + cache read + cache creation summed over turns (what the API
billed); "peak context" is the largest single window the main agent reached.

## The dashboard
When the user wants to *see* it, the overseer dashboard (`/overseer:dashboard`) offers a
**Chronicle** button beside the Board|Atlas coins whenever this plugin is installed; its
**Sync** button runs the same reconciliation.

## Never
- Never edit `sessions.db` by hand or through raw SQL from a session — the CLI is the writer.
- Never add hooks to this plugin. It is pull only by design: a Stop hook that runs code after every turn risks a feedback loop, and `sync` is cheap enough to poll.
