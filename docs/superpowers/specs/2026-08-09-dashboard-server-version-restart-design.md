# Overseer dashboard — server version stamping + restart-on-stale

**Date:** 2026-08-09
**Plugin:** `overseer` (dashboard + hooks)
**Status:** Draft (design) — specced ahead of a context handover; confirm open questions before implementing.

## Problem

The dashboard server (`dashboard/serve.py`) is launched manually and then left
running (often for days, sometimes bound to the LAN). When a session later
starts in a repo whose installed `overseer` is **newer** than the code the
running server was started from, the user keeps looking at a **stale server**
(old backend + old committed `dist/`), with no signal and no refresh.

Today there is **no lifecycle management at all**: `serve.py` has no pidfile,
no lock/singleton, no version stamp; nothing auto-starts it; the backend
exposes no version endpoint. This spec adds the minimum to **detect a stale
running server on session start and restart it** — without auto-starting one
that was never running.

## Design overview

1. **Stamp** the running server: on launch, `serve.py` writes a runtime record.
2. **Expose** the version: add `GET /api/version` (+ include it in the record).
3. **Detect + restart** on session start: a hook compares the running server's
   stamped version to the installed plugin version and, if the server is
   running AND stale, restarts it in place (same host/port/root).

Non-goal: auto-starting the dashboard for repos that never ran it. We only
refresh an already-running, now-stale server.

## B1. Runtime record (single source of truth for "is it running, and what version")

`serve.py` writes, on startup, a JSON record at a stable per-user path:
`$CLAUDE_CONFIG_DIR/overseer/.dashboard.json`:

```json
{
  "pid": 10073,
  "host": "192.168.1.25",
  "port": 8770,
  "root": "/Users/.../pip-skills",
  "version": "0.12.1",           // from plugins/overseer/.claude-plugin/plugin.json
  "started_at": "2026-08-09T20:57"
}
```

- `version` is read from the plugin manifest at launch (same read helper the
  backup manifest uses — factor it into one place).
- Written atomically; removed on clean shutdown (best-effort) — staleness is
  also detected by checking the pid is alive, so a leftover record is safe.
- Single-record assumption: one dashboard per user/config-dir. If a
  multi-dashboard future is wanted, key the record by port (defer).

## B2. Version endpoint

`GET /api/version` → `{version, root, started_at}`. Cheap liveness + version
probe that doesn't depend on reading the record file (confirms the *running*
process's version, not just what a stale file claims).

## B3. Restart-on-stale hook (SessionStart)

A new hook (or an addition to overseer's hooks) that runs on session start:

1. Read `.dashboard.json`. If absent → **do nothing** (no server managed).
2. If `pid` is not alive → treat as not-running → do nothing (clean the stale
   record).
3. Probe `GET /api/version` on the recorded host:port. **No answer → treat as
   not-running:** delete the record, kill nothing, start nothing. A live pid
   is NOT evidence — the record outlives a reboot, and the pid may by then
   belong to an unrelated process; terminating it would both kill a stranger
   and auto-start a dashboard, which is the stated non-goal.
4. Compare the running version (what the probe reports; the record's `version`
   fills in only an answer that omits the field) to the **installed** plugin
   version. If installed <= running → do nothing. Version comparison reads the
   leading dotted-numeric run only, and ranks a prerelease/suffix below the
   bare release (`0.22.0-rc1` < `0.22.0`).
5. If installed **>** running → **restart in place**, handed to a **detached
   worker**: kill the old pid, then relaunch `serve.py` with the recorded
   `--host`/`--port`/`--root` (and `--no-browser`). Preserve the LAN binding
   if it was set.
6. Print a one-line systemMessage: `overseer dashboard restarting x.y.z →
   a.b.c` ("restarting", because the hook does not wait for the worker).
7. If the worker kills the old server and the relaunch then fails, it leaves a
   note; the next session's hook reports it as `overseer dashboard restart
   FAILED …` and clears it. A dashboard that is down is never silently down.

Constraints:
- **Fail-open / non-blocking:** never delay or block session start; any error
  → do nothing (except the failure note above, which is the one thing that
  must be said out loud). The hook itself only reads a file and makes one
  short-timeout probe; every wait-on-a-process is the detached worker's.
- **Debounce:** multiple sessions starting at once must not fight to restart.
  Guard with a short lock (an atomic marker with a TTL) so only one session
  performs the restart; others no-op. The lock names its owner, is taken over
  on staleness by rename (never unlink-then-create, which reopens the race),
  and is released only by that owner — the detached worker, when it is done.
- **Respect the binding:** if the old server was LAN-bound, the restart stays
  LAN-bound (carry host/port from the record) — do not silently drop to
  localhost, and do not silently expose a localhost server to the LAN.

## B4. serve.py singleton behaviour (supporting change)

On launch, if `.dashboard.json` points at a server that ANSWERS the probe —
same evidence rule as B3, a live pid alone is never enough — refuse ("already
running at …") or take over after killing it (flag-controlled, `--replace`).
This holds for **any** port, not just the one being claimed: a second launch
elsewhere would otherwise stamp over the live server's record and leave it
unmanaged. A record that does not answer is a leftover: delete it and launch,
signalling nothing. The restart worker uses `--replace`.

The stamp is written from the ASGI lifespan `startup.complete` message, i.e.
after the socket is listening — never before `uvicorn.run` — so a launch that
dies on "address already in use" neither claims to be the running dashboard
nor deletes the real one's record on its way out.

## Edge cases

- Record present, server dead → no-op (+ optional cleanup).
- Version equal or older → no-op (never downgrade-restart).
- Restart fails to rebind (port now taken by something else) → surface the
  error, leave the user to sort it; never crash the session.
- Two repos of different overseer versions on one machine sharing one dashboard
  → last session to start wins the version (documented; the dashboard serves
  one root at a time anyway).
- Killing a server other devices are viewing → brief interruption on restart;
  acceptable and expected.

## Testing

- `serve.py` writes/removes the record; `--replace` takes over a live pid.
- `GET /api/version` returns the running version.
- Restart hook: no record → no-op; dead pid → no-op; equal/older → no-op;
  newer installed → kills + relaunches with the recorded host/port/root;
  lock/debounce prevents double-restart; all fail-open. Use fake pids /
  monkeypatched launch; env pinned to `tmp_path` (see CLAUDE.md test-isolation
  note). No real long-lived servers in tests.

## Open questions (resolve before build)

1. Should the hook ever **auto-start** a dashboard (vs only restart a running
   one)? Default here: **no** — restart-only.
2. Is one-dashboard-per-user the right model, or per-repo/per-port? (Affects the
   record shape.) Default: one per user/config-dir.
3. Which hook event — reuse overseer's existing SessionStart wiring, or a new
   dedicated hook script?
4. Version-compare semantics with the `<label>-<hash>` central scheme + custom
   `central_dir` — confirm the record path is still single/global per config
   dir.

## Version impact

Minor `overseer` bump (serve.py record + `/api/version` + restart hook) and
marketplace bump.
