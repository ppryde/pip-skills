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
installed as a plugin the scripts live under the plugin root). Every verb prints JSON. It needs
Python 3.10 or later; an older interpreter prints a one-line JSON error and exits 2.

```bash
python .../scripts/cli.py <verb>
```

## Sync first
The store only knows what has been synced. Run `sync` before answering a question about
usage when `status` shows `synced_at` is stale. `sync` stats every transcript on disk and
ingests only the files that moved, but it also reads configured Docker volumes (`docker`),
pulls configured remote boxes (`ssh`), and refreshes list prices from the network at most
daily. Set `CHRONICLE_NO_REMOTES=1` to skip the ssh pulls and `CHRONICLE_NO_PRICING_REFRESH=1`
to skip the price fetch. `backfill` is the same verb for a first run.

If the user works in a dev container whose Claude config lives in a Docker named volume (e.g.
`wf-state`) and its sessions are missing or stale, run `volumes add <name>` once:
`sync` then reads the volume in place, read-only, on every run. Do not reach for the legacy
`pull-volume` copy — it goes stale the day nobody re-runs it.

## Answering questions
- **Totals for a window / repo:** `summary --days N [--root <main repo root>]` — totals,
  per-day series, by-model breakdown, tool leaderboard, and session-shape quantiles
  (turns, prompts, span, peak context, transcript size at p50 / p90 / max). The window
  selects SESSIONS active in it: `totals` and `by_model` are whole-session sums for those
  sessions, so a session that began before the window counts in full. Spend inside the window
  is `sum(by_day[*].cost_usd)`; say which of the two you are quoting.
- **Which sessions:** `sessions --days N [--root R] [--limit N]` — most recent first, each
  with turns, prompts, tool calls, token totals, peak context, subagents, compactions, span.
- **One session in depth:** `session <id>` — the per-turn context series (spot the growth
  curve and where compactions landed), tools used, and per-subagent totals. `agent <id> <agent_id>`
  does the same for one subagent.
- **Store health:** `status` — path, row counts, last sync.

| Verb | Use |
|---|---|
| `sync` / `backfill` | ingest what moved (`--full` re-reads everything) |
| `summary`, `sessions` | windowed reports; accept `--days N` or `--since ISO`, `--root R`, `--branch B`, `--account UUID` |
| `session <id>`, `agent <id> <agent>` | one session / subagent in depth |
| `repos` | repo roots seen, with session counts; the `--root` value comes from here |
| `accounts` | account uuids seen, with session counts; the `--account` value comes from here |
| `limits` | deduplicated usage-limit hits and the tokens burned reaching each |
| `status` | path, row counts, last sync |
| `pricing status` (also `refresh`, `backfill`, `seed`) | list-price history behind the cost figures |
| `volumes`, `remotes` | configured Docker volumes / ssh boxes |
| `permits` | what subagents were allowed, denied and asked, per skill and agent type; pass `--json` for the structure (`--days N`, `--since 30d`, `--skill`, `--agent-type`). Counts and fixed category names only. Run `sync` first (and `sync --full` once to backfill older sessions) |
| `dedupe` | collapse calls stored twice (dry run unless `--apply`) |

`--days 0` means no window (all history).

### Keep the output small
`sessions` defaults to `--limit 200` and `session <id>` on a long session prints every turn.
Pass `--limit 10` to `20`, and extract only the keys you need rather than reading the whole
JSON (for instance, read only `totals` and the last seven `by_day` entries of `summary --days 7`). Avoid a raw `session <id>` on a
long session; ask for the part you need.

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
