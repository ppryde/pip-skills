# Census — Status-Line Session Store — Design Spec

**Date:** 2026-07-11
**Status:** Approved design (pending spec review)
**Supersedes framing of:** WF-007 (`vigil context/session measurement`) — the three issues WF-007 raised are resolved by consuming census rather than patching vigil's transcript guessing.

## Context

Vigil measures live context usage by **reconstructing** the transcript path: it slugifies `cwd`
into `~/.claude/projects/<slug>/*.jsonl` and sums the latest `usage` record (`vigil/scripts/context.py`).
Three defects surfaced during the overseer dashboard build (WF-007):

1. **Worktree blindness** — inside a git worktree the reconstructed slug directory does not exist
   (verified: `~/.claude/projects/-Users-...-worktrees-overseer-orchestration` is absent), so
   `find_transcript` returns `None` → `ctx unknown`.
2. **Wrong window / over-report** — the percentage divides by a hardcoded 200 000, but a session may
   run an extended 1 000 000-token window; the measured "105%" was a window mismatch, not cumulative
   summing (the current code already keeps only the *latest* usage record, not the whole file).
3. **No rate-limit view** — vigil cannot see the 5-hour / 7-day plan limits at all.

All three are already computed by Claude Code and handed to the **status line** on stdin every turn:
`transcript_path`, `context_window.{used_percentage,context_window_size,current_usage}`,
`exceeds_200k_tokens`, and `rate_limits.{five_hour,seven_day}`
(source: <https://code.claude.com/docs/en/statusline.md>, verified against the live doc).

The status line is the **only** real-time surface that exposes rate limits — there is no hook payload,
CLI command, or transcript field for them. The user's existing `~/.claude/statusline-command.sh`
already renders these values and already stashes the *full* payload to a session-keyed side-channel
(`~/.claude/statusline-cache/<session_id>.json`) for an agent-ui watcher — but keyed by opaque
`session_id`, with **no way to find "the payload for this worktree."** That missing worktree index is
the whole gap.

This project extracts a **standalone, reusable plugin — `census`** — that ingests the status-line
payload and persists it in a single worktree-indexed store, consumed by both agent-ui and the
pip-skills tools (vigil, the overseer dashboard). One writer (the status line), many readers.

The name: a **census** is the recorded state of every soul, enumerated and indexed — the Book of
Numbers counted the people tribe by tribe. This plugin enumerates every live session and sets down
its vitals, indexed by worktree. It records; it does not broadcast.

### Not available from the status line (explicitly out of scope)

- **Per-model limits** (e.g. a Fable-specific cap). `rate_limits` exposes exactly two windows —
  `five_hour` and `seven_day` — with no model dimension. A Fable/Opus availability cap is surfaced
  only in the TUI footer, never in the payload. Census cannot persist what CC does not emit.
- **Ad-hoc / overage counters.** None exist beyond the two windows plus the fixed
  `exceeds_200k_tokens` boolean.

### Decisions already made

| Decision | Choice | Rationale |
|---|---|---|
| Ownership | A **new standalone plugin `census`**, not a vigil-internal fix | Reused by both agent-ui and pip-skills; single owner of status-line persistence |
| Store shape | **One JSON file**, `~/.claude/census/status.json` | User's call; keeps the store trivially discoverable and greppable |
| Top-level vs per-session | `limits` hoisted to top level; **full payload stored per session** | Rate limits are account-global (identical across sessions); context/token usage is per-session. "Pull it all" — store the whole payload verbatim so any future CC field is captured with no schema change |
| Session key | Keyed by `session_id`, with resolved `worktree_cwd` as a field | `session_id` is unique (two sessions can share a worktree); a reader helper resolves the freshest entry **by worktree cwd** — the index the user asked for |
| Concurrency | Read-modify-write under **`fcntl.flock`** in a Python ingest tool, atomic temp+mv | The status line fires per-turn in every session concurrently; a single shared file needs a lock. `fcntl.flock` works on macOS (shell `flock` does not) |
| Injection | One guarded line piping `$input` into `census ingest` | Mirrors the existing agent-ui side-channel block; never blocks or breaks the render |
| Stack | **Pure stdlib** Python, quarantine-safe | Matches vigil's ethos; ingest/merge/read unit-testable with no CC running |
| Distribution | Lives in `plugins/census/`; agent-ui installs/vendors it | pip-skills is the canonical home; agent-ui consumes the same store file |

## 1. What census is

A standalone plugin with one job: **record the Claude Code status-line payload into a single
worktree-indexed store, safely, on every turn — and let anything read it back.**

Three surfaces:

- `census ingest` — stdin → store (the writer; wired into the status line).
- `census read` — store → stdout (the reader CLI).
- `census.store` — importable module (the reader API for vigil / the dashboard).

Everything is **quarantine-safe**: any read/parse/lock/write failure is swallowed and exits 0.
A broken store can never break the status-line render or the CLI it piggybacks on.

## 2. The store

Single file, `$CLAUDE_CONFIG_DIR/census/status.json` (default `~/.claude/census/status.json`;
override the whole path with `CENSUS_STORE`). Rooting at `CLAUDE_CONFIG_DIR` is what keeps **multiple
accounts isolated** — see §11:

```json
{
  "version": 1,
  "limits": {
    "five_hour": { "used_percentage": 23.5, "resets_at": 1738425600 },
    "seven_day": { "used_percentage": 41.2, "resets_at": 1738857600 },
    "updated_at": 1738420000
  },
  "sessions": {
    "<session_id>": {
      "worktree_cwd": "/Users/me/repo/.claude/worktrees/featureX",
      "updated_at": 1738420000,
      "payload": { "...": "the full status-line payload, verbatim" }
    }
  }
}
```

- **`limits`** — the account-global rate-limit windows, hoisted from session `rate_limits` but gated on a
  **future `resets_at`**. The status line only refreshes `rate_limits` after an API response, so a dormant
  session (open TUI, no recent API call) keeps writing a fresh store entry whose `rate_limits` is frozen
  against a long-dead window — a naive last-write-wins hoist lets that fossil clobber the current figure.
  So only windows whose `resets_at` is in the future are hoisted (and merged per-window, newest write
  winning), and readers likewise drop any window whose reset time has since passed. Absent-safe: a payload
  with no `rate_limits` (non-Pro/Max, or pre-first-response) leaves the existing block untouched.
- **`sessions[session_id].payload`** — the entire payload, stored verbatim ("pull it all").
- **`worktree_cwd`** — resolved once at ingest (see §3) so readers index by worktree without
  re-deriving it.
- **`updated_at`** — ingest wall-clock (epoch seconds), used for freshness / staleness and to pick
  the newest session when several share a worktree.

## 3. Resolving `worktree_cwd`

The index key. Resolution order, first present wins:

1. `worktree.path` — set for `--worktree` sessions.
2. `workspace.current_dir` (falling back to `cwd`) — for `workspace.git_worktree` sessions and the
   plain case. This is the worktree's own directory, which is exactly the index we want.

The raw value is normalised (`os.path.realpath`) so symlinked and trailing-slash variants collapse to
one key.

## 4. Ingest — `census ingest`

```
printf '%s' "$payload" | census ingest
```

1. Read stdin; `json.loads`. On failure → exit 0 (write nothing).
2. Require `session_id`; if absent → exit 0.
3. Acquire an exclusive `fcntl.flock` on `<store>.lock` (created beside the store). Bounded wait; on
   lock failure → exit 0.
4. Load the existing store (missing/corrupt → start from an empty skeleton).
5. Merge:
   - Upsert `sessions[session_id]` = `{worktree_cwd, updated_at, payload}`.
   - **Context-preservation guard:** if the incoming `context_window.current_usage` /
     `used_percentage` is null (the post-`/compact` and pre-first-call gap), retain the prior entry's
     `payload.context_window` rather than storing the null — so readers never regress to "unknown"
     mid-session.
   - If incoming `rate_limits` present → refresh top-level `limits`; else leave as-is.
6. Prune sessions whose `updated_at` is older than a TTL (default 24h) so the file cannot grow without
   bound as sessions come and go.
7. Atomic write: temp file in the same dir + `os.replace`. Release the lock.

Every step is guarded; the command's contract is "best-effort, never raises, always exits 0."

## 5. Reader — `census read` / `census.store`

- `census read --worktree <cwd>` → the freshest session entry whose `worktree_cwd` matches (by
  normalised path), merged with top-level `limits`, as JSON. Missing → prints `{}`, exit 0.
- `census read --session <id>` → that specific entry.
- `census read --limits` → just the top-level `limits`.
- Importable: `census.store.latest_for_worktree(cwd) -> dict | None`,
  `census.store.limits() -> dict | None`. These are what vigil and the dashboard call.

Readers apply a **staleness horizon**: an entry older than a configurable window (default 90s, ~1.5×
the status line's 60s `refreshInterval`) is reported with a `stale: true` marker so a consumer can
show "ctx unknown (stale)" rather than a frozen number from a dead session.

## 6. Consumers

- **vigil** — `cmd_context` reads `census.store.latest_for_worktree(root)` first; the token count and
  percentage come from `context_window.used_percentage` + `context_window_size` (fixing the hardcoded
  200k). The existing transcript-slug path remains as a **fallback** when census has no entry (census
  not installed, or no status line configured), so vigil degrades to today's behaviour rather than
  regressing. This resolves WF-007 #1 and #2.
- **overseer dashboard** — reads census per worktree to show live ctx%, model, PR status, and the
  shared 5h/7d limit gauges. Resolves WF-007 #3.
- **agent-ui watcher** — points at the same `~/.claude/census/status.json` instead of the
  session-keyed side-channel; gets worktree indexing for free.

## 7. Injection into the existing status line

One guarded line added to `~/.claude/statusline-command.sh`, alongside the existing side-channel
block (which may later be retired in favour of census):

```bash
# --- census: record this session's payload to the worktree-indexed store ---
printf '%s' "$input" | census ingest 2>/dev/null || true
```

`|| true` and `2>/dev/null` guarantee a missing/broken census can never fail the render. Census adds a
one-line install/uninstall helper (`census install-statusline` / `--uninstall`) that idempotently adds
or removes this block by a sentinel comment, so users don't hand-edit.

## 8. Bonus fields captured for free ("pull it all")

Because the whole payload is stored, consumers get these with no further census work:

| Field | Consumer use |
|---|---|
| `model.display_name` / `model.id` | per-session model (Opus / Fable / Sonnet) |
| `context_window.context_window_size` | correct % for extended 1M-token windows |
| `session_name` | human label instead of UUID |
| `pr.number` / `pr.url` / `pr.review_state` | worktree ↔ PR + review state on the dashboard |
| `agent.name` | whether the session runs under `--agent` |
| `cost.*` | session cost / burn |
| `effort.level`, `thinking.enabled` | reasoning effort / extended thinking |

## 9. Plugin layout

```
plugins/census/
  .claude-plugin/plugin.json
  README.md
  pyproject.toml                 # pure stdlib; test/lint deps only
  commands/                      # optional: /census-status inspector
  scripts/
    __init__.py
    cli.py                       # ingest / read / install-statusline
    store.py                     # load, merge, atomic write, flock, prune, readers
    resolve.py                   # worktree_cwd resolution + path normalisation
  tests/
    test_ingest.py               # merge, limits hoist, absent rate_limits, null current_usage guard
    test_concurrency.py          # concurrent flock writers do not lose entries
    test_read.py                 # latest_for_worktree, staleness, --limits
    test_resolve.py              # worktree.path vs workspace.current_dir vs cwd, realpath collapse
```

## 10. Testing strategy

Pure-stdlib, no CC required. Feed captured payload fixtures (worktree, main-tree, non-Pro/Max
without `rate_limits`, post-`/compact` with null `current_usage`, extended 1M window) into `ingest`
and assert the store shape. Concurrency test forks N processes writing distinct `session_id`s at once
and asserts no lost updates (the flock contract). Reader tests cover worktree resolution, staleness
marking, and the vigil-fallback path.

## 11. Multi-account isolation

A single laptop often runs multiple Claude accounts — e.g. a personal Max account and a work API
account — separated by `CLAUDE_CONFIG_DIR` (personal → `~/.claude-personal`, work → default
`~/.claude`). Both accounts may point their `statusLine` at the **same** script, so a hardcoded store
path would commingle them — and worse, leak the Max account's top-level `rate_limits` onto the API
account's worktrees (API sessions carry no `rate_limits`, so they never overwrite the leaked values).

Census roots the store at `CLAUDE_CONFIG_DIR` (fallback `~/.claude`): personal writes to
`~/.claude-personal/census/status.json`, work to `~/.claude/census/status.json`. The status line
inherits the launching account's `CLAUDE_CONFIG_DIR`, so one shared script routes each write to the
right store automatically; readers inside a session inherit the same env and read their own account's
store. Separate files, separate locks, separate limits — no cross-account interference.

(A consumer that deliberately wants a *unified* cross-account view — e.g. a dashboard showing both —
can enumerate the known config dirs and read each store; the default is strict isolation.)

## 12. Out of scope

- Any per-model or Fable-specific limit (not emitted by CC).
- Rendering — census persists; the status line and dashboard render.
- Rewriting the user's status-line script beyond adding the one guarded block.
- Migrating/removing the existing agent-ui side-channel (left in place; can be retired later).
