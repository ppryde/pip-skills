# census

Records the Claude Code **status-line payload** into a per-session, worktree-indexed store, so any tool
can read a session's live context %, model, PR status, and 5-hour / 7-day rate-limit usage.

One writer (the status line, every turn), many readers (vigil, the overseer dashboard, agent-ui).
Pure stdlib, quarantine-safe: a broken store can never break the status-line render.

## Why

The status line is the only real-time surface Claude Code exposes that carries `transcript_path`,
`context_window.*` (live window + size + `used_percentage`), and `rate_limits.{five_hour,seven_day}`.
But it is handed to a shell command on stdin and not otherwise persisted. Census captures it and
indexes it **by worktree cwd**, which nothing else does — so a reader can ask "what is the live
context for *this* worktree" without reconstructing transcript paths (which breaks inside git
worktrees).

## Store

A folder at `$CLAUDE_CONFIG_DIR/census/` — i.e. `~/.claude/census/` by default, or
`~/.claude-personal/census/` when that account sets `CLAUDE_CONFIG_DIR` (override the folder
entirely with `CENSUS_STORE`):

```
census/
  limits.json                 account rate limits, forward-only merge
  sessions/<session_id>.json  one file per session, atomic replace
  status.json.v1-migrated     present for 7 days after a v1 migration, then deleted
```

`sessions/<session_id>.json`:

```json
{ "version": 2, "worktree_cwd": "<abs path>", "updated_at": 1738420000, "active_at": 1738419700,
  "branch": "<git branch or null>", "tmux_pane": "%3", "payload": { "...verbatim..." } }
```

`limits.json`:

```json
{ "version": 2,
  "five_hour": { "used_percentage": 23.5, "resets_at": 1738425600 },
  "seven_day": { "used_percentage": 41.0, "resets_at": 1738800000 },
  "updated_at": 1738420000 }
```

**No lock; Windows-safe.** Each session writes only its own file (temp file plus `os.replace`), so
sessions never contend. Only `limits.json` is shared, and its merge only ever moves forward, so a
lost race costs at most one refresh of a lower figure and can never stick wrong. A session id that
is not a safe filename (`[A-Za-z0-9._-]+`, up to 128 chars) is refused.

`census read` prints the unchanged v1 view (`{version: 1, limits, sessions}`), so readers see no
difference.

- Rate limits are account-global, so they live in their own `limits.json`. Not last-write-wins:
  usage only rises until a window resets, so a later `resets_at` wins outright (new window)
  and within one window the higher percentage wins. That ordering reads the readings
  themselves, so it needs neither write order nor a trustworthy clock, and a dormant
  session's frozen figure can never displace a working session's current one.
  Boundaries within a minute of each other count as the same window, and a reset more
  than ten days out is refused as a corrupt or wrong-unit value (ten rather than eight,
  so a clock running a couple of days behind still accepts a genuine seven-day window).
- **Known tradeoff:** because the higher percentage wins, the figure LATCHES for the rest
  of a window. If the denominator changes mid-window — a plan upgrade, extra capacity
  purchased, or limits raised — usage legitimately falls, and the stored figure stays at
  the old peak until that window resets. Up to five hours for `five_hour`, up to seven
  days for `seven_day`. The error is conservative (it overstates usage, never understates
  it), which is the safe direction for a "how close am I" gauge, but it is real.
  Both windows are fixed rather than rolling, which is what makes the latch bounded:
  measured across 155 captured payloads, `seven_day` boundaries are always Sunday 20:00
  local and exactly one week apart, and `five_hour` boundaries are quantised to ten
  minutes and bit-identical across concurrent sessions.
- The full payload is stored per session — any future CC field is captured with no schema change.
- `updated_at` is "last rendered": the status line reruns on `refreshInterval` as well as after
  each API response, so a dormant TUI keeps refreshing it. `active_at` is "last active": it moves
  only when the payload's activity counters (prompt id, cost, API duration, token totals, cache
  requests) change between ingests. Readers derive `stale` (not rendered for 90s — dead or closed)
  and `idle` (still rendering, no activity for 10 min — open, nobody working) from the two.
- Sessions are keyed by `session_id` (one file each); readers resolve the freshest entry **by worktree cwd**.

## Upgrading from v1

Automatic. The first `census` run on a v1 `status.json` splits it into per-session files and
`limits.json`, then renames it to `status.json.v1-migrated`, kept for 7 days and then deleted. Run
`census install --yes` once per account to replace an old hand-made launcher with the managed one.

## Usage

```bash
census install            # dry run: what it would add or replace
census install --yes      # launcher at ~/.local/bin/census + status-line block
census uninstall --yes    # remove both; --purge also deletes this account's data
```

`--shim` or `--statusline` limits either command to one half. Both are idempotent. The older
`census install-statusline [--uninstall]` still works as a **deprecated alias** for one release.

Or add the one line yourself, after your script slurps stdin into `$input`:

```bash
printf '%s' "$input" | census ingest 2>/dev/null || true
```

Read it back:

```bash
census read --worktree "$PWD"      # freshest session for this worktree, + limits
census read --session <id>
census read --limits               # just the account rate limits
census read                        # the whole store
```

From Python:

```python
from scripts import store
entry = store.latest_for_worktree(cwd)   # None if unknown; carries `stale` and `idle` flags
limits = store.limits()
```

## Guarantees

- **Concurrency-safe without a lock:** one file per session, replaced atomically, so every session
  writing each turn cannot lose each other's entries (and it works on Windows).
- **Degrades quietly:** missing `rate_limits` (non-Pro/Max, or pre-first-response) leaves the last
  known limits untouched; a blank context window (post-`/compact`) keeps the prior reading rather
  than reporting unknown.
- **Staleness:** readers flag entries older than ~90s so a consumer can distinguish a live reading
  from one frozen by a dead session.
- **Multi-account safe:** the store is rooted at `CLAUDE_CONFIG_DIR`, the same boundary Claude Code
  uses to separate accounts. A personal (Max) account and a work (API) account each get their own
  store folder — sessions and rate limits never commingle, even when both share one status-line script.
- **Records each session's git branch (fail-safe):** ingest resolves the current branch for the
  worktree cwd at record time; if that resolution fails for any reason the entry's `branch` is
  simply `null` rather than blocking the ingest or breaking the status line.
