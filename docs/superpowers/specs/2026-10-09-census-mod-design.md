# census-mod — census v2 recorded and drawn by a Claude Code mod

## Why

The status line is a command Claude Code re-runs every 60 s in every session,
idle or not: ~0.5 runs/s across ~20 sessions here (measured 2026-10-04). The
bash line costs ~320 ms a run (~16 % of a core, continuously); `census
statusline` cut that to ~72 ms (~3.5 %). A mod runs inside Claude Code and acts
on events, so the steady-state cost is about zero.

The one blocker found on 2026-10-05 is gone: the prompt-cache hit rate is in
`turn.complete`'s usage, and the cache expiry is the last call plus the TTL the
transcript records (`cache_creation.ephemeral_1h_input_tokens` /
`ephemeral_5m_input_tokens`; context-vigil-mod's `core/cache-ttl.ts` already
reads it).

## Goals

1. **Record** every main session into the census v2 store with no status line:
   the same `sessions/<sid>.json` and `limits/<account>.json` files, written by
   census's own `census ingest` (one writer implementation, no TypeScript port
   of the store).
2. **Draw** the status line in the band above the prompt: the same segments,
   rules and look as `census statusline` (`plugins/census/scripts/render.py` is
   the reference).
3. **Liveness without a heartbeat:** readers tell "open but idle" from "gone" by
   the session's process, not by a 90 s write cadence.
4. **Cheap external calls:** git and gh run only when something they report can
   have changed, with the smallest possible queries.
5. **Shadow mode first:** run beside the existing status line, writing to a
   separate census dir, so the two stores can be compared before cutover.

## Non-goals

- Replacing census's store, CLI or `census statusline` (non-mod users, Windows,
  vigil-lite still use them).
- context-vigil-mod: separate plugin, untouched.
- Recording subagents or `-p` runs (possible later: `turn.complete` carries
  `agentId`; a status line never saw them).

## Shape

`plugins/census-mod/` in pip-skills, a mod (hooks/register.tsx + core/), tests in
`tests/census_mod/`, run by `tests/run-mods.sh` (add it to `MODS`). It requires
the census plugin's CLI (found through census's `cli.path` pointer under the
account's census dir, else `CENSUS_CLI`); without it the mod draws but records
nothing and says so once.

### 1. The payload it records

The mod builds a JSON object in the **status-line payload shape** (the keys
census reads: `session_id`, `transcript_path`, `cwd`, `workspace.current_dir`,
`workspace.project_dir`, `worktree.path` when present, `model.{id,display_name}`,
`context_window.{used_percentage,context_window_size}`, `cost.{total_cost_usd,
total_duration_ms}`, `rate_limits.{five_hour,seven_day,spend_limit}.{used_percentage,resets_at}`,
`prompt_cache.{hit_ratio,requests,misses,warm,expires_at}`, `session_name`,
`pr.{number,url,review_state}`, `version`) from `$.session.usage()`,
`$.session.model()`, `$.session.cwd()`, `$.session.id()`, turn usage and the
caches below, plus a new block:

```json
"census_mod": { "version": 1, "pid": 22695, "proc_start": "…", "event": "turn.complete" }
```

and pipes it to `census ingest` through `$.process.run(argv, { stdin })`. Census
stores the payload verbatim, so readers see the same fields they see today.
Field names follow the real status-line payload exactly; check a live
`~/.claude-personal/census/sessions/*.json` before choosing a spelling.

### 2. When it records (no heartbeat)

| Event | Why |
|---|---|
| `session.start`, and a `/clear` (classic `SessionStart` with source `clear`, which gives a new session id) | register the session; `/clear` starts a new census entry |
| `turn.complete` (main thread only: no `agentId`) | cost, context, cache, limits moved |
| rate-limit change (`session.measure`, when a window's percentage or reset changes) | limits for the dashboard |
| model switch, cwd change, branch change, PR change | the fields readers show changed |
| cache-cold timer: last main `turn.complete` + TTL | write `prompt_cache.warm: false` so readers know the cache went cold |
| `session.end` | write `census_mod.ended: <reason>` so a clean exit is "gone" at once |

Writes are coalesced: at most one ingest per 2 s per session; a pending write
carries the latest state. Ingest runs from `$.clock.after(0)`, never awaited by
a hook the turn waits on.

### 3. Liveness (replaces the 90 s heartbeat)

- The mod records `census_mod.pid` and `proc_start`, taken from Claude Code's
  own session registry (`<config dir>/sessions/<pid>.json`, the entry whose
  `sessionId` is this session; agent-roster reads the same registry).
- **census change (in `plugins/census`):** a reader computing `stale` for an
  entry whose payload has `census_mod.pid` treats it as stale when the session
  ended (`census_mod.ended` set) or the process is gone: `os.kill(pid, 0)`
  fails, or the registry file `<config>/sessions/<pid>.json` is missing or
  carries a different `procStart` (PID reuse). Otherwise it is live however old
  `updated_at` is. Entries without `census_mod` keep the 90 s rule. `idle`
  (10 min without activity) is unchanged.
- The check is same-machine only; that is every current reader.

### 4. Drawing

- `ui.render` `AbovePrompt` band, two lines by default, same segments, glyphs,
  colours and thresholds as `render.py`. Segment order from
  `CENSUS_STATUSLINE_SEGMENTS` (same syntax) so one setting drives both.
- Yield while `hasSurvey` is true (field notes). Redraw on the same events as
  recording plus a 30 s clock tick for countdowns only (`⟳` resets), which
  redraws but never records.
- Data: `$.session.usage()` (context %, rate limits incl. `spend_limit`, cost,
  `startedAt` for $/hr), `$.session.model()`, git cache, gh cache, cache figures.
- Cache figures: hit rate from the last main `turn.complete` usage
  (`cache_read / (cache_read + cache_creation + input)`), also a session total;
  `warm` until last turn + TTL; TTL from the transcript tail as cache-ttl.ts
  does (default 5 min when unknown).

### 5. git — minimal and event-driven

- One call: `git --no-optional-locks status --porcelain=2 --branch -uno` (no
  untracked scan; ✏️ already excludes untracked files).
- Refresh only when: `.git/HEAD` or the index changes (classic SessionStart
  `watchPaths` → `FileChanged`, resolved for worktrees as context-vigil-mod's
  `core/git.ts` does), a `tool.call` of Edit/Write/Bash completes, or the cwd
  changes. Coalesce to one run per 1 s.

### 6. gh — minimal and rare

- What we check: does this branch have an **open** PR, its **number**, **url**
  and **review decision**. Nothing else (no CI checks, no comments).
- Call: `gh pr list --head <branch> --state open --limit 1 --json number,url,reviewDecision`.
- Cached per repo+branch in `$.store`; refreshed only on branch change, after a
  Bash tool call whose command contains `git push` or `gh pr`, or when older than
  10 min and the session is active. Timeout 5 s; a failure keeps the cached
  value and backs off 10 min. `gh` missing or not logged in → no PR segment,
  one log line.
- `review_state`: `APPROVED` → `approved`, `CHANGES_REQUESTED` →
  `changes_requested`, `REVIEW_REQUIRED` → `review_required`, empty → omitted
  (match the spelling census already stores from the real payload).

### 7. Session name

From the transcript (as context-vigil-mod's `core/name.ts` does), refreshed on
`turn.complete`.

### 8. Shadow mode and cutover

- `CENSUS_MOD_STORE` (a census dir) overrides where it records; set it to e.g.
  `~/.claude-personal/census-shadow` to run beside the status line.
- `census-mod compare` (a small script, or a `census read` against both dirs)
  diffs the two views for live sessions: keys present, values within tolerance.
- Cutover: unset `CENSUS_MOD_STORE`, remove `statusLine` from settings.

## Testing

Fake-engine tests (as context-vigil-mod's `tests/world.tsx`): recording on each
event, coalescing, payload shape (golden), session end, cache-cold timer,
git/gh refresh rules and argv, gh failure backoff, drawing per segment, survey
yield. Census side: pytest for the PID liveness rule (live pid, dead pid, reused
pid via registry `procStart`, ended flag, entries without `census_mod`), with
the registry and store under `tmp_path`.

## Ratified changes (2026-10-09, Fable review; supersede the text above)

**Events.** Register on `classic.SessionStart` for every `source`
(`startup|resume|clear|compact|fork`), gated on `isInteractive` (no `-p` runs).
`session.start` re-fires on hot reload and never after `/clear`: make it
idempotent and re-arm timers there (timers die on reload). Main thread =
`e.agentId === undefined`. Model and cwd changes: `classic.PostModelSwitch`,
`classic.CwdChanged`. `session.end`: run the final ingest with `timeoutMs` under
the hook's `next.budget`. `transcript_path` and `version` come from the classic
hook input / the session registry.

**Census CLI discovery.** `<census dir>/cli.path` (census dir = `CENSUS_STORE`
else `$CLAUDE_CONFIG_DIR/census`) → `CENSUS_CLI` → `census` on PATH. Run it as
`[python3, cli.py, 'ingest']` for a `.py`, else the executable. In shadow mode
pass `CENSUS_STORE=<CENSUS_MOD_STORE>` in the child env (ingest honours it);
the shadow dir gets its own `cli.path`, `limits/`, sweep.

**Liveness rules (census side).** Compare the recorded `proc_start` string with
the registry file's `procStart` string only (it is `ps lstart` text in another
time zone; never compare with `ps`). `os.kill(pid, 0)`: success or `EPERM` =
alive; `ESRCH` = gone; refuse pid ≤ 1. Registry files vanish on clean exit but
outlive crashes, so a missing file = gone, a different `procStart` = gone.

**Activity and counters.** census's `_activity_fingerprint` drives
`active_at`/`idle` from `prompt_id`, `cost.total_cost_usd`,
`cost.total_api_duration_ms`, `context_window.total_input_tokens` /
`total_output_tokens` and `prompt_cache.requests` — read store.py for exact
paths. The mod keeps per-session counters (turns → `prompt_cache.requests`,
summed TurnUsage → total input/output tokens) in `$.store` keyed by session id
so they survive reloads, and fills `cost.*` from `usage().cost` when present.

**Context.** `context_window.used_percentage` = `usage().context.percent`; when
absent send null (census keeps the prior value).

**Rate limits.** `usage().rateLimits[]` has ISO `resetsAt` and decimal
`percentUsed`: convert to `rate_limits.<kind>.{used_percentage, resets_at}` with
`resets_at` as epoch seconds, or census drops the window.

**Cache.** `e.usage` is optional (aborted/error turns): skip those. Hit rate per
turn from the turn's usage (state in code whether that is the turn's sum, per
the typings); session ratio from summed counters. `classic.PostCompact` forces
`warm: false` (a compact cold-starts the prefix). Emit `prompt_cache.ttl`
(`"5m"`/`"1h"`) and epoch `expires_at` as the real payload does; `misses` is
not measurable — omit it.

**PR.** `review_state` uses the stored spellings: `APPROVED → approved`,
`REVIEW_REQUIRED → pending`, `CHANGES_REQUESTED → changes_requested`, empty →
key omitted. Run gh with `cwd` = the worktree.

**Session name.** The custom-title transcript grep context-vigil-mod uses
(`hooks/register.tsx` around line 790), not `core/name.ts`.

**git.** Port `gitcache.parse_status`'s detached and unborn rules.

**Band.** Always `await next(e)` and nest the other mods' output (context-vigil-mod
returns its own tree when its bar shows); yield to `hasSurvey`; respect
`maxRows`/`bodyColumns`; call `$.ui.invalidate('ui.render')` after data
changes. Map render.py's ANSI colours to `Text` colours; port the `/` line
syntax of `CENSUS_STATUSLINE_SEGMENTS`.
