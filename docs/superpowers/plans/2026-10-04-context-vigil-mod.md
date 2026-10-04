# context-vigil-mod Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `context-vigil-mod` — context handover as a Claude Code mod (pure TypeScript, no Python, no tmux, no status line) — that runs side by side with classic context-vigil.

**Architecture:** A mod plugin at `plugins/context-vigil-mod/`. `hooks/register.tsx` is the effectful shell and the ONLY file that touches `$`; every decision lives in pure, unit-tested modules under `core/` that take facts and return decisions. All shared data types live in the `$.state` contract `types/index.d.ts`, which core modules import with `import type … from '../types'`.

**Tech Stack:** TypeScript ES modules run by the Claude Code mod host; `claude-code` (types + `atom/read/update`), `claude-code/testing` (`test`, `expect`, `mock`), `claude plugin validate`, `claude plugin test`, `tsc`; bash + `jq` for the install script; pytest for the install-script test.

**Spec:** `docs/superpowers/specs/2026-10-04-context-vigil-mod-design.md` (approved; HEAD 811b27e). Executors read both.

## Global Constraints

- Plugin name `context-vigil-mod`, defined once as `NAME` in `core/name.ts` plus `.claude-plugin/plugin.json`.
- Commands `/vho`, `/vhandoff`, `/vsetup`; tool `vigil_handover` (full name `mcp__context-vigil-mod__vigil_handover`). Never `/ho`, `/handoff` (classic's).
- `$` appears ONLY in `hooks/register.tsx`. Helpers that take `$` are top-level `function` declarations in that same file (the validator rejects `$` passed anywhere else). `core/*.ts` import nothing from `claude-code` except types.
- Shared types live in `types/index.d.ts`; core files `import type { … } from '../types'`. Imports are extensionless (`'../core/arming'`).
- Files written only under `$CLAUDE_CONFIG_DIR/context-vigil-mod/` (`CLAUDE_CONFIG_DIR` read once via `$.env.get("CLAUDE_CONFIG_DIR")`, fallback `$HOME/.claude`). Never another account's directory.
- Settings and cross-session flags in `$.store` (per account). Live session values in `$.state`.
- `$.command.run({ command: 'clear' })` and `$.prompt.submit(...)` are always started from a `$.clock.after(...)` timer, never awaited inside a hook the turn is waiting on.
- Defaults (spec §6): nudge 35% (+5% steps), vigil bar On, auto mode Off, idle window 30 min, last light Off (threshold 25%), limits On (trigger 95%, windows `seven_day` + `spend_limit`), RC auto-clear unanswered (treated as No).
- Working window: agent activity within the last **2 min**. RC countdown **30 s**; no RC clear within **2 min** of the last `bridge` prompt. Last-light lead **300 s**, TTL 1 h.
- Setup-card headers ≤ 12 UTF-16 code units; 2–4 options per question including "Tell me more".
- Every user-facing string comes from `core/voice.ts`, emoji-led. Exempt from the emoji rule: option labels a person picks (`On`, `35%`, `Resume from handover`, …) and prompt texts addressed to the model.
- `$.state` atom refs must spell `plugin` and `key` as string literals (the validator requires literals), so the atoms repeat `'context-vigil-mod'`; T11's test pins that literal to `NAME`.
- Plugin prompts carry no origin argument: `PromptSubmitArgs` omits `origin`, and the engine stamps every `$.prompt.submit` as `{ kind: 'plugin', name: 'context-vigil-mod' }`. Hooks read `e.origin.kind`.
- `$.ui.ask` is not an op event: it runs as a `tool.call` of `AskUserQuestion` whose result is `{ questions, answers: { [question]: label } }` (claude-code-tools typings). The test world answers it there.
- Every clear that consumes a pending handover renames the new session to the handover's `session_name` via a mod-run `/rename` (spec §3 step 4; Task 11a).
- Stage only your own files: `git add <exact paths>`, never `git add -A` / `.`; tasks run one at a time in one worktree.
- Tests never touch a real config dir: shell tests use the in-memory world in `tests/world.tsx` (`CLAUDE_CONFIG_DIR=/cfg`); the install-script test uses pytest `tmp_path`.
- Gates for every task: `claude plugin validate plugins/context-vigil-mod`, `claude plugin test plugins/context-vigil-mod`, `bash plugins/context-vigil-mod/scripts/typecheck.sh` — all clean.
- Every commit message ends with these two lines (every commit step below already carries them):
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_016Fj6V4wmyLYFK41Ed3YAqf`
- Work in the worktree `/Users/philip.pryde/repos/pip-skills/.claude/worktrees/context-vigil-mod` on branch `feat/context-vigil-mod`. Never push.

## Review Focus

1. **Two sessions on one account at once** (two tmux windows) — each must keep its own event log, handovers, pending handover and early-stop marks; a shared day file rewritten whole by two writers would lose lines. → Task 1 (`name.ts` tests) pins per-session paths; Task 11 test "events go to a per-session day file"; Task 12 test "a pending handover is keyed by its session".
2. **The threshold after a `/clear`** — context falls back near 0%, and the next crossing of 35% must nudge again, not be swallowed by the old `lastNudged`. → Task 5 test `nextThreshold after reset`; Task 12 test "clear resets lastNudged".
3. **The model never calls `vigil_handover`, or calls it with missing fields** — a person would expect a retry, then a visible failure, and nothing cleared. → Task 5 tests `parseFields` rejections; Task 12 tests retry-once-then-notice.
4. **A hot reload or restart mid-flow** (pending handover, running countdown) — module variables reset, so the pending handover must come back from `$.state`/`$.store`, never be silently dropped. → Task 12 test "a pending handover is keyed by its session" (restored from `$.store` at session start); Task 11 test "a fresh session start resets module caches".
5. **A corrupted or hand-edited settings blob in `$.store`** — must fall back field-by-field to defaults, never crash the mod. → Task 1 tests `loadSettings`.

## Spec ambiguities resolved in this plan

- **Event log path:** the spec's `events/<yyyy-mm-dd>.jsonl` would have two sessions rewriting one file (`$.fs.write` writes whole files). Resolved: `events/<yyyy-mm-dd>/<session>.jsonl` — one writer per file; dashboards glob the day folder.
- **"Working" signal:** `turn.step` is a streaming event (`StreamingEventName = 'turn.step' | 'process.spawn'`), so the shell uses `tool.call` and `turn.complete` as agent-activity signals instead. A long turn makes tool calls; a turn without tool calls ends in `turn.complete`.
- **Classic detection:** the spec's `.vigil/sessions/` is wrong for current classic. Classic writes session records to `$CLAUDE_CONFIG_DIR/context-vigil/sessions/<session_id>.json` and its hook commands contain `/scripts/context-vigil" hook `. The interlock checks those.
- **Last-light return question:** asking through the model would itself pay the cold cache last light exists to avoid. Resolved: `$.ui.ask` (the engine's AskUserQuestion dialog, no model turn). Setup cards still go through the model's AskUserQuestion as the spec says.
- **Cache TTL:** the mod API exposes no live cache TTL. Default 1 h; updated from `classic.PostModelSwitch` input `cache_ttl` (`'5m' | '1h'`) when it fires.
- **`register.tsx`, not `register.ts`:** the shell draws the vigil bar in JSX, so the hooks module is `.tsx` (`hooks/hooks.json` names `./register.tsx`).
- **Install refuses while classic is installed** (stricter than spec §7's "stands down"): installing into an account that still has classic's hooks would do nothing but stand down, so `install.sh` stops and says to uninstall classic first. The runtime stand-down stays for the case the script cannot see (a classic session record).
- **Per-session keys (pre-flight F4/F5):** the pending handover lives in `$.store` under `pending:<session>`, so it survives a restart only for that session (`claude --resume` keeps the id); early-stop "fired" marks live in `$.state` per session (a restarted process may re-fire once).
- **Countdown Cancel and the RC question (F24):** the bar shows the RC countdown with a Cancel button (hotkey `0`); any prompt cancels too. The RC question is asked when auto mode would first arm in a session whose last human prompt came over `bridge` (spec §2), not at the first clear.
- **`ahead` dropped (F30):** git runs two commands (branch, status); nothing consumes ahead while the status-line band is parked.
- **Early `prompt.edit` band for last light (spec §4 "may"):** not built in v1; listed under Deferred.

## Parallel waves

Execution runs one task at a time (shared worktree and index); the waves give the order and the dependencies. Within wave 1: T6 after T3 (imports `WaitReason` from `voice.ts`), T7 after T4 (imports `classifyOrigin` from `arming.ts`). Every task's gate runs the whole suite, so each task leaves it green.

```
Wave 0 (serial):   T1 scaffold + contract + settings + name + typecheck
Wave 1 (parallel after T1; disjoint files):
                   T2 probes (owner-assisted, throwaway, records PROBES.md)
                   T3 voice + eventlog   T4 arming    T5 handover    T6 surfaces (clear gate)
                   T7 last-light         T8 limits    T9 setup       T10 git + interlock
                   T16 install scripts
Wave 2 (serial, all edit hooks/register.tsx; needs wave 1 + T2 results):
                   T11 shell foundation → T12 handover + bar → T13 last light → T14 limits → T15 setup + RC ask
Wave 3:            T17 docs + owner smokes → T18 final whole-branch review
Deferred:          interlock removal + classic retirement; status-line band (parked)
```

## File structure

```
plugins/context-vigil-mod/
  .claude-plugin/plugin.json      manifest (name, version, description, "types")
  .gitignore                      ignores .claude-plugin/types/ (engine-laid typings)
  tsconfig.json                   extends ./.claude-plugin/types/tsconfig.json (editor)
  hooks/hooks.json                { "modules": ["./register.tsx"] }
  hooks/register.tsx              THE shell — only user of `$`
  types/index.d.ts                $.state contract + every shared type
  core/name.ts                    NAME, TOOL, COMMANDS, paths
  core/settings.ts                DEFAULTS, STORE_KEY, loadSettings
  core/voice.ts                   every user-facing string
  core/eventlog.ts                event record shape + jsonl line
  core/arming.ts                  origin classification, activity, mode, transitions
  core/handover.ts                thresholds, tool schema, parse, render, prompt texts
  core/surfaces.ts                the clear gate incl. Remote Control rules
  core/last-light.ts              timer arithmetic, fire conditions, return hold
  core/limits.ts                  latch, early stop, resume hops, HH:MM
  core/setup.ts                   setup steps, cards, answers, "Tell me more"
  core/git.ts                     git argv, parse, staleness
  core/interlock.ts               classic detection (TEMPORARY)
  scripts/typecheck.sh            tsc gate
  scripts/install.sh              user-level install/uninstall (CLAUDE_CODE_PLUGIN_DIRS)
  tests/*.test.ts(x)              one per core module + shell tests
  tests/world.tsx                 in-memory engine world for shell tests
  README.md  SMOKES.md  PROBES.md
tests/context_vigil_mod/test_install.py   pytest for scripts/install.sh
```

---

### Task 1: Scaffold, contract, settings, names, typecheck gate

**Files:**
- Create: `plugins/context-vigil-mod/.claude-plugin/plugin.json`, `.gitignore`, `tsconfig.json`, `hooks/hooks.json`, `hooks/register.tsx`, `types/index.d.ts`, `core/name.ts`, `core/settings.ts`, `scripts/typecheck.sh`
- Test: `plugins/context-vigil-mod/tests/settings.test.ts`, `tests/name.test.ts`

**Interfaces:**
- Produces (every later task relies on these exact names):
  - `types/index.d.ts`: `Window`, `RcAnswer`, `Settings`, `Who`, `Mode`, `Activity`, `Fields`, `Snapshot`, `Git` (`{ branch, dirty }`), `RateLimit`, `Latch`, `PendingReason`, `Pending` (with `session`), `Awaiting`, `StepId`, `EventKind`, `EventRecord`, and the `PluginState['context-vigil-mod']` contract (17 keys).
  - `core/name.ts`: `NAME`, `TOOL`, `TOOL_FULL`, `COMMANDS`, `configRoot(env)`, `handoverPath(root, session, n)`, `eventsPath(root, day, session)`, `classicSessionPath(root, session)`.
  - `core/settings.ts`: `DEFAULTS: Settings`, `STORE_KEY = 'settings'`, `pendingKey(session): string` (`'pending:<session>'`), `loadSettings(raw: unknown): Settings`.

- [ ] **Step 0: Load the mod-authoring skill** — invoke the `plugin-authoring` skill once (it lays this build's typings at `/private/tmp/claude-*/bundled-skills/*/*/plugin-authoring/types/claude-code.d.ts`, which `scripts/typecheck.sh` uses). Skim `reference.md` beside it.

- [ ] **Step 1: Write the manifest, hooks file, ignore and tsconfig**

`plugins/context-vigil-mod/.claude-plugin/plugin.json`:
```json
{
  "name": "context-vigil-mod",
  "version": "0.1.0",
  "description": "Context handover as a Claude Code mod: nudge, auto handover, last light, limits — no tmux, no status line.",
  "types": "./types/index.d.ts"
}
```
`plugins/context-vigil-mod/hooks/hooks.json`:
```json
{ "modules": ["./register.tsx"] }
```
`plugins/context-vigil-mod/.gitignore`:
```
.claude-plugin/types/
```
`plugins/context-vigil-mod/tsconfig.json`:
```json
{ "extends": "./.claude-plugin/types/tsconfig.json" }
```

- [ ] **Step 2: Write the contract** `plugins/context-vigil-mod/types/index.d.ts`:
```ts
export type Window = 'seven_day' | 'spend_limit'
export type RcAnswer = 'unanswered' | 'yes' | 'no'

export type Settings = {
  nudgeAt: number
  step: number
  bar: boolean
  auto: boolean
  idleMin: number
  lastLight: boolean
  lastLightAt: number
  limits: boolean
  limitPct: number
  limitWindows: Window[]
  rcAutoClear: RcAnswer
}

export type Who = 'human' | 'agent' | 'headless'
export type Mode = 'attended' | 'auto' | 'idle'

export type Activity = {
  lastHumanAt: number | null
  lastHumanOrigin: string | null
  lastBridgeAt: number | null
  lastAgentAt: number | null
  headless: boolean
}

export type Fields = {
  goal: string
  state: string
  decisions: string
  next_step: string
  open_questions: string
  failed_attempts: string
}

export type Snapshot = {
  session: string
  at: string
  cwd: string
  branch: string | null
  dirty: string[]
  edited: string[]
  contextPct: number | null
}

export type Git = { branch: string | null; dirty: string[] }

export type RateLimit = { kind: string; percentUsed: number; resetsAt?: string }
export type Latch = { kind: string; resetsAtMs: number } | null

export type PendingReason = 'threshold' | 'request' | 'last_light' | 'limit'
export type Pending = {
  session: string
  path: string
  reason: PendingReason
  markdown: string
  resume: boolean
  followUp: string | null
  createdAt: number
}

// A handover the model has been asked to write and has not written yet. `started` turns
// true when the instruction prompt itself passes prompt.submit, so only ITS turn's
// turn.complete counts as a missed attempt.
export type Awaiting = { reason: PendingReason; resume: boolean; attempts: number; started: boolean }

export type StepId =
  | 'nudge' | 'bar' | 'auto' | 'idle' | 'last_light' | 'last_light_at'
  | 'limits' | 'limit_pct' | 'limit_windows' | 'rc'

export type EventKind =
  | 'arm' | 'disarm' | 'threshold' | 'bar' | 'handover.requested' | 'handover.written'
  | 'guard.wait' | 'clear' | 'resume' | 'last_light.fired' | 'last_light.choice'
  | 'limit.latched' | 'limit.cleared' | 'limit.early_stop' | 'rc.answer' | 'setup'
  | 'standdown'

export type EventRecord = { ts: string; session: string; kind: EventKind } & Record<string, unknown>

declare module 'claude-code' {
  interface PluginState {
    'context-vigil-mod': {
      activity: Activity
      mode: Mode
      contextPct: number | null
      lastNudged: number | null
      barShown: boolean
      barDismissed: boolean
      pending: Pending | null
      awaiting: Awaiting | null
      deferred: Awaiting | null
      handoverCount: number
      firedEarlyStops: string[]
      latch: Latch
      countdownEndsAt: number | null
      lastLightArmed: boolean
      lastApiAt: number | null
      standDown: boolean
      rcAsked: boolean
    }
  }
}
```

- [ ] **Step 3: Write the failing tests**

`plugins/context-vigil-mod/tests/settings.test.ts`:
```ts
import { describe, expect, test } from 'claude-code/testing'
import { DEFAULTS, STORE_KEY, loadSettings, pendingKey } from '../core/settings'

test('store keys', () => {
  expect(STORE_KEY).toBe('settings')
  expect(pendingKey('s1')).toBe('pending:s1')
})

describe('loadSettings', () => {
  test('nothing stored gives the defaults', () => {
    expect(loadSettings(undefined)).toEqual(DEFAULTS)
    expect(loadSettings(null)).toEqual(DEFAULTS)
    expect(loadSettings('junk')).toEqual(DEFAULTS)
  })
  test('the spec defaults', () => {
    expect(DEFAULTS).toEqual({
      nudgeAt: 35, step: 5, bar: true, auto: false, idleMin: 30,
      lastLight: false, lastLightAt: 25, limits: true, limitPct: 95,
      limitWindows: ['seven_day', 'spend_limit'], rcAutoClear: 'unanswered',
    })
  })
  test('valid fields override, the rest stay default', () => {
    const s = loadSettings({ auto: true, idleMin: 60, limitPct: 90 })
    expect(s.auto).toBe(true)
    expect(s.idleMin).toBe(60)
    expect(s.limitPct).toBe(90)
    expect(s.nudgeAt).toBe(35)
  })
  test('invalid fields fall back field by field', () => {
    const s = loadSettings({ nudgeAt: 250, bar: 'yes', idleMin: -3, limitWindows: ['seven_day', 'bogus', 'seven_day'], rcAutoClear: 'maybe' })
    expect(s.nudgeAt).toBe(35)
    expect(s.bar).toBe(true)
    expect(s.idleMin).toBe(30)
    expect(s.limitWindows).toEqual(['seven_day'])
    expect(s.rcAutoClear).toBe('unanswered')
  })
  test('the defaults object is never shared', () => {
    const s = loadSettings(undefined)
    s.limitWindows.push('spend_limit')
    expect(DEFAULTS.limitWindows).toEqual(['seven_day', 'spend_limit'])
  })
})
```
`plugins/context-vigil-mod/tests/name.test.ts`:
```ts
import { expect, test } from 'claude-code/testing'
import { COMMANDS, NAME, TOOL_FULL, classicSessionPath, configRoot, eventsPath, handoverPath } from '../core/name'

test('names', () => {
  expect(NAME).toBe('context-vigil-mod')
  expect(TOOL_FULL).toBe('mcp__context-vigil-mod__vigil_handover')
  expect(COMMANDS).toEqual({ handover: 'vho', handoff: 'vhandoff', setup: 'vsetup' })
})
test('config root prefers CLAUDE_CONFIG_DIR, falls back to HOME/.claude', () => {
  expect(configRoot({ CLAUDE_CONFIG_DIR: '/cfg/', HOME: '/h' })).toBe('/cfg')
  expect(configRoot({ HOME: '/h' })).toBe('/h/.claude')
  expect(configRoot({})).toBe('.claude')
})
test('paths are per session and stay inside the mod folder', () => {
  expect(handoverPath('/cfg', 's1', 2)).toBe('/cfg/context-vigil-mod/handovers/s1-2.md')
  expect(eventsPath('/cfg', '2026-10-04', 's1')).toBe('/cfg/context-vigil-mod/events/2026-10-04/s1.jsonl')
  expect(classicSessionPath('/cfg', 's1')).toBe('/cfg/context-vigil/sessions/s1.json')
})
```

- [ ] **Step 4: Run to see them fail**

Run: `claude plugin test plugins/context-vigil-mod`
Expected: FAIL — cannot resolve `../core/settings` / `../core/name`.

- [ ] **Step 5: Implement**

`plugins/context-vigil-mod/core/name.ts`:
```ts
export const NAME = 'context-vigil-mod'
export const TOOL = 'vigil_handover'
export const TOOL_FULL = `mcp__${NAME}__${TOOL}`
export const COMMANDS = { handover: 'vho', handoff: 'vhandoff', setup: 'vsetup' } as const

export function configRoot(env: { CLAUDE_CONFIG_DIR?: string; HOME?: string }): string {
  if (env.CLAUDE_CONFIG_DIR) return env.CLAUDE_CONFIG_DIR.replace(/\/+$/, '')
  return env.HOME ? `${env.HOME.replace(/\/+$/, '')}/.claude` : '.claude'
}

export function handoverPath(root: string, session: string, n: number): string {
  return `${root}/${NAME}/handovers/${session}-${n}.md`
}

export function eventsPath(root: string, day: string, session: string): string {
  return `${root}/${NAME}/events/${day}/${session}.jsonl`
}

// TEMPORARY (interlock): where classic context-vigil keeps a session record.
export function classicSessionPath(root: string, session: string): string {
  return `${root}/context-vigil/sessions/${session}.json`
}
```
`plugins/context-vigil-mod/core/settings.ts`:
```ts
import type { Settings, Window } from '../types'

export const STORE_KEY = 'settings'

// Per session: a second session on the account must never see or wipe this one's handover.
export function pendingKey(session: string): string {
  return `pending:${session}`
}

export const DEFAULTS: Settings = {
  nudgeAt: 35, step: 5, bar: true, auto: false, idleMin: 30,
  lastLight: false, lastLightAt: 25, limits: true, limitPct: 95,
  limitWindows: ['seven_day', 'spend_limit'], rcAutoClear: 'unanswered',
}

const isPct = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && v >= 1 && v <= 100
const inRange = (v: unknown, lo: number, hi: number): v is number =>
  typeof v === 'number' && Number.isFinite(v) && v >= lo && v <= hi

export function loadSettings(raw: unknown): Settings {
  const s: Settings = { ...DEFAULTS, limitWindows: [...DEFAULTS.limitWindows] }
  if (!raw || typeof raw !== 'object') return s
  const r = raw as Record<string, unknown>
  if (isPct(r.nudgeAt)) s.nudgeAt = r.nudgeAt
  if (inRange(r.step, 1, 50)) s.step = r.step
  if (typeof r.bar === 'boolean') s.bar = r.bar
  if (typeof r.auto === 'boolean') s.auto = r.auto
  if (inRange(r.idleMin, 1, 1440)) s.idleMin = r.idleMin
  if (typeof r.lastLight === 'boolean') s.lastLight = r.lastLight
  if (isPct(r.lastLightAt)) s.lastLightAt = r.lastLightAt
  if (typeof r.limits === 'boolean') s.limits = r.limits
  if (isPct(r.limitPct)) s.limitPct = r.limitPct
  if (Array.isArray(r.limitWindows)) {
    const ok = r.limitWindows.filter((w): w is Window => w === 'seven_day' || w === 'spend_limit')
    s.limitWindows = [...new Set(ok)]
  }
  if (r.rcAutoClear === 'yes' || r.rcAutoClear === 'no' || r.rcAutoClear === 'unanswered') s.rcAutoClear = r.rcAutoClear
  return s
}
```
`plugins/context-vigil-mod/hooks/register.tsx` (a valid empty shell; Task 11 fills it):
```tsx
import type { Register } from 'claude-code'

// The effectful shell: the ONLY file that touches `$`. Decisions live in ../core.
export const register: Register = _on => {}
```
`plugins/context-vigil-mod/scripts/typecheck.sh`:
```bash
#!/usr/bin/env bash
# tsc gate. Uses the engine-laid typings when the mod has been loaded once
# (.claude-plugin/types/), else this build's typings from the plugin-authoring skill.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -f .claude-plugin/types/claude-code/index.d.ts ]; then exec tsc -p .; fi
types=$(ls -t /private/tmp/claude-*/bundled-skills/*/*/plugin-authoring/types/claude-code.d.ts 2>/dev/null | head -1 || true)
if [ -z "$types" ]; then
  echo "typecheck: no claude-code typings — load the plugin-authoring skill (or this mod) once" >&2
  exit 2
fi
tmp=$(mktemp -d)
here=$(pwd)
cat > "$tmp/tsconfig.json" <<EOF
{ "compilerOptions": { "target": "es2023", "lib": ["es2023"], "types": [],
    "module": "esnext", "moduleResolution": "bundler", "strict": true,
    "noUncheckedIndexedAccess": true, "noEmit": true, "skipLibCheck": true,
    "jsx": "react", "jsxFactory": "h", "jsxFragmentFactory": "Fragment" },
  "include": ["$types", "$here/hooks", "$here/core", "$here/types", "$here/tests"] }
EOF
exec tsc -p "$tmp/tsconfig.json"
```
Then `chmod +x plugins/context-vigil-mod/scripts/typecheck.sh`.

- [ ] **Step 6: Run all gates**

Run: `claude plugin validate plugins/context-vigil-mod && claude plugin test plugins/context-vigil-mod && bash plugins/context-vigil-mod/scripts/typecheck.sh`
Expected: validation passes (an `author` warning is fine); all tests pass; tsc prints nothing and exits 0.

- [ ] **Step 6b: Prove the toolchain on the constructs later tasks use** (F21). Temporarily replace `hooks/register.tsx` with this stub (it uses JSX through the global `h`, imported `atom/read/update` given `$`, and a `readonly` argv to `$.process.run`), run validate + typecheck, then restore the empty shell from Step 5:
```tsx
import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'
const shownA = atom({ plugin: 'context-vigil-mod', key: 'barShown' } as const, false)
const ARGV = ['git', 'status', '--porcelain'] as const
export const register: Register = on => {
  on('turn.complete', async ($, e, next) => {
    await update($, shownA, () => true)
    await $.process.run(ARGV)
    return next(e)
  })
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (!(await read($, shownA))) return next(e)
    const { Box, Text } = $.ui.resolve(e)
    return <Box><Text>stub</Text></Box>
  })
}
```
Run: `claude plugin validate plugins/context-vigil-mod && bash plugins/context-vigil-mod/scripts/typecheck.sh`
Expected: both clean (this combination passed in a scratch plugin while planning). If either refuses, stop and report the message — Tasks 11–15 depend on these constructs. Then restore the empty shell and re-run the Step 6 gates.

- [ ] **Step 7: Commit**
```bash
git add plugins/context-vigil-mod/.claude-plugin/plugin.json plugins/context-vigil-mod/.gitignore plugins/context-vigil-mod/tsconfig.json plugins/context-vigil-mod/hooks plugins/context-vigil-mod/types plugins/context-vigil-mod/core/name.ts plugins/context-vigil-mod/core/settings.ts plugins/context-vigil-mod/scripts/typecheck.sh plugins/context-vigil-mod/tests/settings.test.ts plugins/context-vigil-mod/tests/name.test.ts
git commit -m "feat(context-vigil-mod): scaffold, state contract, settings and names" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Fj6V4wmyLYFK41Ed3YAqf"
```

---

### Task 2: Early verification probes (owner-assisted, throwaway)

Answers spec §9 before wave 2 depends on it. The probe mod is throwaway and lives OUTSIDE the repo; only the results file is committed.

**Files:**
- Create (throwaway, not committed): `~/.claude-personal/dev-mods/<session>/cvm-probe/` (or any `--plugin-dir` folder outside the repo) with `.claude-plugin/plugin.json`, `hooks/hooks.json`, `hooks/register.ts`
- Create (committed): `plugins/context-vigil-mod/PROBES.md`

**Interfaces:**
- Produces: `PROBES.md` with a verdict per question (sections 1–7). Task 11's `notify()`, Task 12's clear/inject path, Task 13's `$.ui.ask` and Task 15's answer capture and follow-up cards follow it.

- [ ] **Step 1: Write the probe mod** `hooks/register.ts`:
```ts
import type { EngineInterface, Register } from 'claude-code'

// THROWAWAY probe for context-vigil-mod spec §9.
const log: { at: number; step: string; detail?: unknown }[] = []
async function note($: EngineInterface, step: string, detail?: unknown) {
  log.push({ at: Date.now(), step, detail })
  await $.fs.write(`${$.plugin.root}/probe-log.json`, JSON.stringify(log, null, 2)).catch(() => {})
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const r = await next(e)
    await $.command.register({ name: 'cvm-probe-notice', description: 'PROBE: send a toast + a transcript log line' })
    await $.command.register({ name: 'cvm-probe-tool', description: 'PROBE: register a tool and ask the model to call it' })
    await $.command.register({ name: 'cvm-probe-ask', description: 'PROBE: model AskUserQuestion, capture answers' })
    await note($, 'loaded')
    return r
  })
  on('command.run', { command: 'cvm-probe-notice' }, async $ => {
    $.ui.toast('🧪 probe toast — did this reach the phone?')
    $.ui.log('🧪 probe log line — did this reach the phone?')
    await note($, 'notice sent')
    return { text: 'probe: toast + log sent' }
  })
  on('command.run', { command: 'cvm-probe-tool' }, async $ => {
    const { tool } = await $.tool.register({
      name: 'probe_echo', description: 'Echo a word back. Call it when asked to by the probe.',
      inputSchema: { type: 'object', properties: { word: { type: 'string' } }, required: ['word'] },
    })
    await note($, 'tool registered', tool)
    $.clock.after(0, () => void $.prompt.submit({ text: 'Call the probe_echo tool with word "pelican". Nothing else.' }))
    return { text: `probe: registered ${tool}` }
  })
  on('tool.call', async ($, e, next) => {
    const input = e as unknown as { tool: string; [k: string]: unknown }
    if (input.tool.endsWith('__probe_echo')) {
      await note($, 'probe_echo called', input)
      return { result: `echo: ${String(input.word)}` } as never
    }
    const r = await next(e)
    if (input.tool === 'AskUserQuestion') await note($, 'AskUserQuestion seen', { input, result: r })
    return r
  })
  on('command.run', { command: 'cvm-probe-ask' }, async $ => {
    $.clock.after(0, () => void $.prompt.submit({
      text: 'Call AskUserQuestion with exactly one question: header "🧪 Probe", question "Pick one?", options "A" and "B". Nothing else.',
    }))
    return { text: 'probe: asking' }
  })
  on('classic.Stop', async ($, e, next) => {
    await note($, 'classic.Stop', e)
    return next(e)
  })
  // F20: $.ui.ask, a mod-run /clear, default plugin prompt origin, { drop }, tool.call context.
  on('session.start', async ($, e, next) => {
    const r = await next(e)
    await $.command.register({ name: 'cvm-probe-uiask', description: 'PROBE: $.ui.ask dialog' })
    await $.command.register({ name: 'cvm-probe-clear', description: 'PROBE: mod-run /clear from a timer' })
    await $.command.register({ name: 'cvm-probe-drop', description: 'PROBE: drop your next prompt, then re-submit it' })
    return r
  })
  on('command.run', { command: 'cvm-probe-uiask' }, async $ => {
    $.clock.after(0, () => {
      void $.ui.ask('🧪 Probe: pick one?', ['Resume from handover', 'Carry on'])
        .then(answer => note($, 'ui.ask resolved', answer))
        .catch(err => note($, 'ui.ask rejected', String(err)))
    })
    return { text: 'probe: ui.ask scheduled' }
  })
  on('command.run', { command: 'cvm-probe-clear' }, async $ => {
    await note($, 'mod clear scheduled', { session: await $.session.id() })
    $.clock.after(1000, () => {
      void $.command.run({ command: 'clear' }).then(r => note($, 'mod clear resolved', r)).catch(err => note($, 'mod clear rejected', String(err)))
    })
    return { text: 'probe: /clear in 1 s' }
  })
  let dropNext = false
  on('command.run', { command: 'cvm-probe-drop' }, async () => {
    dropNext = true
    return { text: 'probe: your next message will be held, then re-sent' }
  })
  on('prompt.submit', async ($, e, next) => {
    await note($, 'prompt.submit origin', e.origin)
    if (dropNext && e.origin.kind !== 'plugin') {
      dropNext = false
      const held = e.text
      $.clock.after(1500, () => { void $.prompt.submit({ text: held }).then(() => note($, 'held prompt re-sent', held)) })
      return { drop: 'probe: held' }
    }
    return next(e)
  })
  on('classic.SessionStart', async ($, e, next) => {
    await note($, 'classic.SessionStart', { source: e.source, session: await $.session.id() })
    const r = await next(e)
    return e.source === 'clear' ? { ...r, additionalContext: [...(r.additionalContext ?? []), 'PROBE: the secret word is HERON.'] } : r
  })
}
```
In the `probe_echo` branch of the `tool.call` hook, return `{ result: \`echo: ${String(input.word)}\`, context: ['PROBE CONTEXT: the codeword is OSPREY.'] } as never` (tests whether a tool result's `context` reaches the model).
Write `.claude-plugin/plugin.json` `{ "name": "cvm-probe", "version": "0.0.1", "description": "THROWAWAY probe" }` and `hooks/hooks.json` `{ "modules": ["./register.ts"] }`. Run `claude plugin validate <probe folder>` — must pass.

- [ ] **Step 2: Owner runs the probe** (the auto-mode classifier forbids an agent driving another session — hand these steps to the owner verbatim):
  1. Start `claude --plugin-dir <probe folder>` in a scratch repo; connect the phone via Remote Control.
  2. Run `/cvm-probe-notice` from the terminal, then again from the phone. Note: did the toast and/or the log line appear on the phone? In the terminal?
  3. Run `/cvm-probe-tool`. Note: did the model call `probe_echo` in the same session (the tool should be offered from the next prompt on)?
  4. Run `/cvm-probe-ask`, answer "B" (once in the terminal, once from the phone). The probe records the `AskUserQuestion` input and result.
  5. After step 3, ask the model: "What codeword did the probe tool give you?" — OSPREY means a tool result's `context` reaches the model.
  6. Run `/cvm-probe-uiask`; pick "Resume from handover" in the terminal; repeat from the phone.
  7. Run `/cvm-probe-drop`, then send `hello there` — it should vanish, then re-appear about 1.5 s later as a plugin prompt.
  8. Run `/cvm-probe-clear` and keep the prompt box empty — after 1 s the session clears; then ask "What is the secret word?" (HERON means the mod-run clear fired `classic.SessionStart` with source `clear` and the injection landed).

- [ ] **Step 3: Read `probe-log.json` and write `plugins/context-vigil-mod/PROBES.md`** with exactly these sections, each with the observed answer and the decision:
```markdown
# context-vigil-mod probes (spec §9) — <date>

## 1. Notice reaching the phone
Observed: toast → terminal <yes/no>, phone <yes/no>; ui.log line → terminal <yes/no>, phone <yes/no>.
Decision: notify() uses <ui.toast | ui.log | both>.

## 2. Registered tool offered next turn
Observed: probe_echo called <yes/no>; result shape accepted: `{ result: string }` <yes/no>.
Decision: vigil_handover served by a `tool.call` hook on TOOL_FULL returning `{ result: string }` (or the observed shape).

## 3. AskUserQuestion answers visible to a tool.call hook
Observed: answers found at <`e.answers` | `r.result.answers` | both>; keyed by <question text | header>; multi-select joined by <", " | ",">.
Decision: `extractAnswers` (Task 9) reads input first, then result — keep, or narrow to the observed path.

## 4. classic.SessionStart source 'clear' after a MOD-RUN /clear
Observed: source <clear/other>; injected context reached the model (HERON) <yes/no>; `command.run` <resolved/rejected: message>.

## 5. tool.call result `context` reaches the model
Observed: OSPREY <yes/no>.
Decision: setup follow-up cards ride `context` on the AskUserQuestion result (Task 15) <keep | switch to $.prompt.submit of the next card>.

## 6. $.ui.ask
Observed: terminal → resolved to <label>; phone → <resolved label | rejected | not shown>.
Decision: last-light return question (Task 13) <keep $.ui.ask | fall back to the model's AskUserQuestion>.

## 7. Plugin prompt origin and { drop }
Observed: a plugin's `$.prompt.submit` reaches hooks with origin <`{ kind: 'plugin', name }` | other>; `{ drop }` held the prompt <yes/no>; re-submit arrived <yes/no>.
```

- [ ] **Step 4: Commit**
```bash
git add plugins/context-vigil-mod/PROBES.md
git commit -m "docs(context-vigil-mod): record spec §9 probe results" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Fj6V4wmyLYFK41Ed3YAqf"
```

---

### Task 3: Voice and event log

**Files:**
- Create: `plugins/context-vigil-mod/core/voice.ts`, `core/eventlog.ts`
- Test: `tests/voice.test.ts`, `tests/eventlog.test.ts`

**Interfaces:**
- Consumes: `EventKind`, `EventRecord` from `../types`.
- Produces: `V` (object of strings/functions below — exact keys); `type WaitReason` (imported by Task 6); `dayKey(ms): string`, `makeRecord(ms, session, kind, fields): EventRecord`, `appendLine(existing, rec): string`.

- [ ] **Step 1: Write the failing tests**

`tests/eventlog.test.ts`:
```ts
import { expect, test } from 'claude-code/testing'
import { appendLine, dayKey, makeRecord } from '../core/eventlog'

test('dayKey is the UTC date', () => {
  expect(dayKey(Date.UTC(2026, 9, 4, 23, 59))).toBe('2026-10-04')
  expect(dayKey(Date.UTC(2026, 0, 2, 0, 0))).toBe('2026-01-02')
})
test('a record carries ts, session, kind and the deciding facts', () => {
  const r = makeRecord(Date.UTC(2026, 9, 4, 12), 's1', 'arm', { idleMs: 1800000, origin: 'composer' })
  expect(r).toEqual({ ts: '2026-10-04T12:00:00.000Z', session: 's1', kind: 'arm', idleMs: 1800000, origin: 'composer' })
})
test('fields never overwrite ts, session or kind', () => {
  const r = makeRecord(0, 's1', 'clear', { kind: 'bogus', session: 'x', ts: 'y' })
  expect(r.kind).toBe('clear')
  expect(r.session).toBe('s1')
  expect(r.ts).toBe('1970-01-01T00:00:00.000Z')
})
test('appendLine adds exactly one JSON line', () => {
  const a = appendLine('', makeRecord(0, 's1', 'arm', {}))
  const b = appendLine(a, makeRecord(1, 's1', 'disarm', {}))
  const lines = b.trimEnd().split('\n')
  expect(lines.length).toBe(2)
  expect(JSON.parse(lines[1] ?? '').kind).toBe('disarm')
  expect(b.endsWith('\n')).toBe(true)
})
test('appendLine repairs a file missing its final newline', () => {
  expect(appendLine('{"a":1}', makeRecord(0, 's', 'arm', {})).split('\n').length).toBe(3)
})
```
`tests/voice.test.ts`:
```ts
import { expect, test } from 'claude-code/testing'
import { V } from '../core/voice'

test('bar strings', () => {
  expect(V.barLine(41, 35, null)).toBe('🕯️ context 41% · threshold 35%')
  expect(V.barLine(41, 35, '14:05')).toBe('🕯️ context 41% · threshold 35% · ⏳ resumes 14:05')
  expect(V.barHandover).toBe('📜 Hand over now')
  expect(V.barLater(45)).toBe('⏰ Remind me at 45%')
  expect(V.barDismiss).toBe('✖ Dismiss')
  expect(V.countdownLine(12)).toBe('🧹 Handing over in 12 s — 0 or send anything to cancel')
  expect(V.cancel).toBe('✖ Cancel')
})
test('every user-facing string is emoji-led', () => {
  const samples = [
    V.nudge(41), V.handoverSaved('/x.md'), V.handoverFailed, V.clearRejected, V.countdownLine(30),
    V.countdownCancelled, V.setupUsage, V.rcAsk, V.pendingOffer('/x.md'), V.waiting('draft'), V.lastLightReady,
    V.lastLightAsk, V.limitLatched('14:05'), V.limitCleared, V.earlyStop('seven_day', 95, '14:05'),
    V.classicActive, V.setupSaved, V.handingOver, V.settingUp, V.cmdHandover, V.cmdSetup,
  ]
  for (const s of samples) expect(/^\p{Extended_Pictographic}/u.test(s)).toBe(true)
})
test('waiting explains every guard reason', () => {
  for (const r of ['draft', 'latched', 'classic', 'rc-unanswered', 'rc-declined', 'rc-holdback', 'countdown', 'countdown-start'] as const) {
    expect(V.waiting(r).length).toBeGreaterThan(5)
  }
})
```

- [ ] **Step 2: Run to see them fail** — `claude plugin test plugins/context-vigil-mod` → FAIL (modules missing).

- [ ] **Step 3: Implement**

`core/eventlog.ts`:
```ts
import type { EventKind, EventRecord } from '../types'

export function dayKey(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10)
}

export function makeRecord(ms: number, session: string, kind: EventKind, fields: Record<string, unknown>): EventRecord {
  return { ...fields, ts: new Date(ms).toISOString(), session, kind }
}

export function appendLine(existing: string, rec: EventRecord): string {
  const base = existing === '' || existing.endsWith('\n') ? existing : `${existing}\n`
  return `${base}${JSON.stringify(rec)}\n`
}
```
`core/voice.ts`:
```ts
// Every user-facing string, emoji-led, in one place.
export type WaitReason =
  | 'draft' | 'latched' | 'classic' | 'rc-unanswered' | 'rc-declined' | 'rc-holdback'
  | 'countdown' | 'countdown-start'

const WAIT: Record<WaitReason, string> = {
  'draft': '✍️ Handover waiting — there is a draft in your prompt box',
  'latched': '⏳ Handover waiting — the usage limit is in force',
  'classic': '🕯️ Handover skipped — classic context-vigil is active here',
  'rc-unanswered': '📱 Handover saved — auto-clear in Remote Control is not switched on (/vsetup rc)',
  'rc-declined': '📱 Handover saved — auto-clear is off for Remote Control sessions',
  'rc-holdback': '📱 Handover waiting — you were active on the phone a moment ago',
  'countdown': '🧹 Handover countdown running — send anything to cancel',
  'countdown-start': '🧹 Handing over in 30 s — send anything to cancel',
}

export const V = {
  barLine: (pct: number, threshold: number, resumes: string | null) =>
    `🕯️ context ${pct}% · threshold ${threshold}%${resumes ? ` · ⏳ resumes ${resumes}` : ''}`,
  barHandover: '📜 Hand over now',
  barLater: (next: number) => `⏰ Remind me at ${next}%`,
  barDismiss: '✖ Dismiss',
  nudge: (pct: number) => `🕯️ Context at ${pct}% — say "hand over" (or /vho) when you're ready 📜`,
  handoverSaved: (path: string) => `📜 Handover saved — ${path}`,
  handoverFailed: '📜 Couldn\'t write a handover — nothing was cleared',
  clearRejected: '🧹 /clear was refused — the handover is still pending; /clear to resume from it',
  countdownLine: (s: number) => `🧹 Handing over in ${s} s — 0 or send anything to cancel`,
  cancel: '✖ Cancel',
  rcAsk: '📱 First Remote Control session with auto mode — one quick question about auto-clear',
  setupUsage: '⚙️ /vsetup [nudge|bar|auto|last-light|limits|rc] — that step name is not one of these',
  countdownCancelled: '🧹 Handover countdown cancelled — the handover is saved; /clear to resume from it',
  pendingOffer: (path: string) => `📜 A handover is waiting (${path}) — /clear to resume from it`,
  waiting: (r: WaitReason) => WAIT[r],
  lastLightReady: '🌅 Last light: a handover is ready 📜 — carry on as normal, or /clear to resume from it ✨',
  lastLightAsk: '🌅 A handover is ready — resume from it (cheap) or carry on with the full conversation (pays the cold cache)?',
  lastLightResume: 'Resume from handover',
  lastLightCarryOn: 'Carry on',
  limitLatched: (hhmm: string) => `⏳ Usage limit reached — resumes ${hhmm}; I won't clear or prompt until then`,
  limitCleared: '⏳ Usage limit lifted — back to normal',
  earlyStop: (kind: string, pct: number, hhmm: string) =>
    `⏳ ${kind} at ${pct}% — handover written; I'll resume after the reset (${hhmm}) if this session is still open`,
  classicActive: '🕯️ Classic context-vigil is active here — context-vigil-mod is standing down',
  setupSaved: '⚙️ context-vigil-mod settings saved',
  handingOver: '📜 Handing over…',
  settingUp: '⚙️ Setting up context-vigil-mod…',
  cmdHandover: '📜 Hand over now (context-vigil-mod)',
  cmdSetup: '⚙️ context-vigil-mod setup — /vsetup [nudge|bar|auto|last-light|limits|rc]',
}
```

- [ ] **Step 4: Run the gates** — validate, test, typecheck: all clean.

- [ ] **Step 5: Commit**
```bash
git add plugins/context-vigil-mod/core/voice.ts plugins/context-vigil-mod/core/eventlog.ts plugins/context-vigil-mod/tests/voice.test.ts plugins/context-vigil-mod/tests/eventlog.test.ts
git commit -m "feat(context-vigil-mod): voice strings and per-session event log lines" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Fj6V4wmyLYFK41Ed3YAqf"
```

---

### Task 4: Arming — origins, activity, mode

**Files:**
- Create: `plugins/context-vigil-mod/core/arming.ts`
- Test: `tests/arming.test.ts`

**Interfaces:**
- Consumes: `Activity`, `Mode`, `Settings`, `Who` from `../types`.
- Produces: `classifyOrigin(kind: string): Who`; `EMPTY_ACTIVITY: Activity`; `type Signal`; `record(a: Activity, s: Signal): Activity`; `WORKING_MS = 120_000`; `mode(a, now, s: Pick<Settings,'idleMin'>): Mode`; `armed(a, now, s: Pick<Settings,'idleMin'|'auto'>): boolean`; `transition(prev: Mode, next: Mode): 'arm' | 'disarm' | null`; `onPhone(a): boolean`.

- [ ] **Step 1: Write the failing test** `tests/arming.test.ts`:
```ts
import { describe, expect, test } from 'claude-code/testing'
import { EMPTY_ACTIVITY, WORKING_MS, armed, classifyOrigin, mode, onPhone, record, transition } from '../core/arming'

const MIN = 60_000
const S = { idleMin: 30, auto: true }

describe('classifyOrigin', () => {
  test('people', () => {
    for (const k of ['composer', 'bridge', 'slack-ping']) expect(classifyOrigin(k)).toBe('human')
  })
  test('headless', () => expect(classifyOrigin('sdk')).toBe('headless'))
  test('the agent working on its own', () => {
    for (const k of ['task-notification', 'scheduled-trigger', 'peer', 'peer-send-message', 'coordinator', 'observer', 'plugin', 'auto-continuation', 'unclassified', 'channel']) {
      expect(classifyOrigin(k)).toBe('agent')
    }
  })
})

describe('record', () => {
  test('a human prompt stamps time and origin; bridge also stamps lastBridgeAt', () => {
    const a = record(EMPTY_ACTIVITY, { kind: 'prompt', origin: 'bridge', at: 5 })
    expect(a).toEqual({ ...EMPTY_ACTIVITY, lastHumanAt: 5, lastHumanOrigin: 'bridge', lastBridgeAt: 5 })
  })
  test('an agent prompt is agent activity', () => {
    expect(record(EMPTY_ACTIVITY, { kind: 'prompt', origin: 'task-notification', at: 7 }).lastAgentAt).toBe(7)
  })
  test('sdk marks the session headless', () => {
    const a = record(EMPTY_ACTIVITY, { kind: 'prompt', origin: 'sdk', at: 1 })
    expect(a.headless).toBe(true)
    expect(a.lastAgentAt).toBe(1)
  })
  test('edits and human commands keep the last origin', () => {
    const a = record(record(EMPTY_ACTIVITY, { kind: 'prompt', origin: 'composer', at: 1 }), { kind: 'edit', at: 9 })
    expect(a.lastHumanAt).toBe(9)
    expect(a.lastHumanOrigin).toBe('composer')
    expect(record(a, { kind: 'human-command', at: 11 }).lastHumanAt).toBe(11)
  })
  test('agent steps', () => expect(record(EMPTY_ACTIVITY, { kind: 'agent-step', at: 3 }).lastAgentAt).toBe(3))
})

describe('mode', () => {
  const human = (at: number) => record(EMPTY_ACTIVITY, { kind: 'prompt', origin: 'composer', at })
  test('engaged within the idle window is attended, whatever the agent does', () => {
    const a = record(human(0), { kind: 'agent-step', at: 10 * MIN })
    expect(mode(a, 10 * MIN, S)).toBe('attended')
  })
  test('idle past the window with the agent working is auto', () => {
    const a = record(human(0), { kind: 'agent-step', at: 31 * MIN })
    expect(mode(a, 31 * MIN, S)).toBe('auto')
  })
  test('the agent counts as working for 2 minutes only', () => {
    const a = record(human(0), { kind: 'agent-step', at: 31 * MIN })
    expect(mode(a, 31 * MIN + WORKING_MS - 1, S)).toBe('auto')
    expect(mode(a, 31 * MIN + WORKING_MS, S)).toBe('idle')
  })
  test('both idle is idle', () => expect(mode(human(0), 40 * MIN, S)).toBe('idle'))
  test('headless is never attended', () => {
    const a = record(record(EMPTY_ACTIVITY, { kind: 'prompt', origin: 'sdk', at: 0 }), { kind: 'edit', at: 1 })
    expect(mode(a, 2, S)).toBe('auto')
  })
  test('armed needs auto mode switched on', () => {
    const a = record(human(0), { kind: 'agent-step', at: 31 * MIN })
    expect(armed(a, 31 * MIN, S)).toBe(true)
    expect(armed(a, 31 * MIN, { ...S, auto: false })).toBe(false)
  })
})

test('transition', () => {
  expect(transition('attended', 'auto')).toBe('arm')
  expect(transition('idle', 'auto')).toBe('arm')
  expect(transition('auto', 'attended')).toBe('disarm')
  expect(transition('auto', 'idle')).toBe('disarm')
  expect(transition('attended', 'idle')).toBe(null)
  expect(transition('auto', 'auto')).toBe(null)
})

test('onPhone follows the last human origin', () => {
  expect(onPhone(record(EMPTY_ACTIVITY, { kind: 'prompt', origin: 'bridge', at: 1 }))).toBe(true)
  expect(onPhone(record(EMPTY_ACTIVITY, { kind: 'prompt', origin: 'composer', at: 1 }))).toBe(false)
  expect(onPhone(EMPTY_ACTIVITY)).toBe(false)
})
```

- [ ] **Step 2: Run to see it fail** — `claude plugin test plugins/context-vigil-mod` → FAIL (`../core/arming` missing).

- [ ] **Step 3: Implement** `core/arming.ts`:
```ts
import type { Activity, Mode, Settings, Who } from '../types'

const HUMAN = new Set(['composer', 'bridge', 'slack-ping'])

export function classifyOrigin(kind: string): Who {
  if (HUMAN.has(kind)) return 'human'
  if (kind === 'sdk') return 'headless'
  return 'agent'
}

export const EMPTY_ACTIVITY: Activity = {
  lastHumanAt: null, lastHumanOrigin: null, lastBridgeAt: null, lastAgentAt: null, headless: false,
}

export type Signal =
  | { kind: 'prompt'; origin: string; at: number }
  | { kind: 'human-command'; at: number }
  | { kind: 'edit'; at: number }
  | { kind: 'agent-step'; at: number }

export function record(a: Activity, s: Signal): Activity {
  switch (s.kind) {
    case 'prompt': {
      const who = classifyOrigin(s.origin)
      if (who === 'human') {
        return { ...a, lastHumanAt: s.at, lastHumanOrigin: s.origin, lastBridgeAt: s.origin === 'bridge' ? s.at : a.lastBridgeAt }
      }
      return { ...a, lastAgentAt: s.at, headless: a.headless || who === 'headless' }
    }
    case 'human-command':
    case 'edit':
      return { ...a, lastHumanAt: s.at }
    case 'agent-step':
      return { ...a, lastAgentAt: s.at }
  }
}

export const WORKING_MS = 120_000

export function mode(a: Activity, now: number, s: Pick<Settings, 'idleMin'>): Mode {
  const engaged = !a.headless && a.lastHumanAt !== null && now - a.lastHumanAt < s.idleMin * 60_000
  if (engaged) return 'attended'
  const working = a.lastAgentAt !== null && now - a.lastAgentAt < WORKING_MS
  return working ? 'auto' : 'idle'
}

export function armed(a: Activity, now: number, s: Pick<Settings, 'idleMin' | 'auto'>): boolean {
  return s.auto && mode(a, now, s) === 'auto'
}

export function transition(prev: Mode, next: Mode): 'arm' | 'disarm' | null {
  if (next === 'auto' && prev !== 'auto') return 'arm'
  if (prev === 'auto' && next !== 'auto') return 'disarm'
  return null
}

export function onPhone(a: Activity): boolean {
  return a.lastHumanOrigin === 'bridge'
}
```

- [ ] **Step 4: Gates** — validate, test, typecheck: clean.

- [ ] **Step 5: Commit**
```bash
git add plugins/context-vigil-mod/core/arming.ts plugins/context-vigil-mod/tests/arming.test.ts
git commit -m "feat(context-vigil-mod): arming — origin classes, activity, attended/auto/idle" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Fj6V4wmyLYFK41Ed3YAqf"
```

---

### Task 5: Handover core — thresholds, tool schema, parse, render, texts

**Files:**
- Create: `plugins/context-vigil-mod/core/handover.ts`
- Test: `tests/handover.test.ts`

**Interfaces:**
- Consumes: `Fields`, `Snapshot`, `Settings`, `PendingReason` from `../types`; `TOOL_FULL` from `../core/name`.
- Produces: `nextThreshold(pct: number, s: Pick<Settings,'nudgeAt'|'step'>, lastNudged: number | null): number | null`; `FIELD_NAMES`; `INPUT_SCHEMA`; `TOOL_DESCRIPTION`; `parseFields(input: Record<string, unknown>): { ok: true; fields: Fields } | { ok: false; error: string }`; `renderHandover(f: Fields, s: Snapshot): string`; `instructionText(reason: PendingReason): string`; `resumeText(path: string): string`; `injectText(markdown: string): string`; `limitResumeText(path: string): string`.

- [ ] **Step 1: Write the failing test** `tests/handover.test.ts`:
```ts
import { describe, expect, test } from 'claude-code/testing'
import { INPUT_SCHEMA, injectText, instructionText, limitResumeText, nextThreshold, parseFields, renderHandover, resumeText } from '../core/handover'

const S = { nudgeAt: 35, step: 5 }

describe('nextThreshold', () => {
  test('below the threshold nothing is due', () => expect(nextThreshold(34, S, null)).toBe(null))
  test('the first crossing', () => expect(nextThreshold(35, S, null)).toBe(35))
  test('a jump lands on the highest step crossed', () => expect(nextThreshold(47, S, null)).toBe(45))
  test('the same step never repeats', () => expect(nextThreshold(39, S, 35)).toBe(null))
  test('the next step is due', () => expect(nextThreshold(40, S, 35)).toBe(40))
  test('after reset (a /clear) the first crossing is due again', () => {
    expect(nextThreshold(12, S, null)).toBe(null)
    expect(nextThreshold(36, S, null)).toBe(35)
  })
})

describe('parseFields', () => {
  const good = { goal: 'g', state: 's', next_step: 'n' }
  test('required fields only; optional ones default to empty', () => {
    expect(parseFields(good)).toEqual({ ok: true, fields: { goal: 'g', state: 's', decisions: '', next_step: 'n', open_questions: '', failed_attempts: '' } })
  })
  test('a missing or blank required field is rejected with its name', () => {
    const r = parseFields({ goal: 'g', state: '  ', next_step: 'n' })
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.error).toContain('state')
  })
  test('a non-string field is rejected', () => {
    const r = parseFields({ ...good, decisions: 42 })
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.error).toContain('decisions')
  })
  test('strings are trimmed', () => {
    const r = parseFields({ goal: ' g ', state: 's', next_step: 'n' })
    expect(r.ok && r.fields.goal).toBe('g')
  })
  test('the schema requires the three core fields', () => {
    expect(INPUT_SCHEMA.required).toEqual(['goal', 'state', 'next_step'])
  })
})

describe('renderHandover', () => {
  const snap = { session: 's1', at: '2026-10-04T12:00:00.000Z', cwd: '/repo', branch: 'main', dirty: ['a.ts'], edited: ['b.ts', 'c.ts'], contextPct: 41 }
  const fields = { goal: 'Ship it', state: 'Half done', decisions: 'Use B', next_step: 'Write tests', open_questions: '', failed_attempts: 'tmux keys' }
  test('sections in order, empty ones left out, snapshot at the end', () => {
    const md = renderHandover(fields, snap)
    expect(md.startsWith('# 📜 Handover — s1 (2026-10-04T12:00:00.000Z)\n')).toBe(true)
    const order = ['## Goal', '## State', '## Decisions', '## Next step', '## Failed attempts', '## Snapshot']
    let at = -1
    for (const h of order) { const i = md.indexOf(h); expect(i).toBeGreaterThan(at); at = i }
    expect(md).not.toContain('## Open questions')
    expect(md).toContain('- branch: main')
    expect(md).toContain('- context: 41%')
    expect(md).toContain('- dirty: a.ts')
    expect(md).toContain('- edited this session: b.ts, c.ts')
  })
  test('unknowns are said plainly', () => {
    const md = renderHandover(fields, { ...snap, branch: null, dirty: [], edited: [], contextPct: null })
    expect(md).toContain('- branch: (not a git repo)')
    expect(md).toContain('- dirty: none')
    expect(md).toContain('- context: unknown')
  })
})

test('texts name the tool and the file', () => {
  expect(instructionText('threshold')).toContain('mcp__context-vigil-mod__vigil_handover')
  expect(instructionText('last_light')).toContain('Do not clear')
  expect(resumeText('/cfg/x.md')).toContain('/cfg/x.md')
  expect(injectText('# H')).toContain('# H')
  const after = limitResumeText('/cfg/x.md')
  expect(after).toContain('/cfg/x.md')
  expect(after).toContain('limit has reset')
  expect(after).not.toContain('injected above')
})
```

- [ ] **Step 2: Run to see it fail** — FAIL (`../core/handover` missing).

- [ ] **Step 3: Implement** `core/handover.ts`:
```ts
import type { Fields, PendingReason, Settings, Snapshot } from '../types'
import { TOOL_FULL } from './name'

export function nextThreshold(pct: number, s: Pick<Settings, 'nudgeAt' | 'step'>, lastNudged: number | null): number | null {
  if (pct < s.nudgeAt) return null
  const crossed = s.nudgeAt + Math.floor((pct - s.nudgeAt) / s.step) * s.step
  if (lastNudged !== null && crossed <= lastNudged) return null
  return crossed
}

export const FIELD_NAMES = ['goal', 'state', 'decisions', 'next_step', 'open_questions', 'failed_attempts'] as const
const REQUIRED = ['goal', 'state', 'next_step'] as const

const DESCRIBE: Record<(typeof FIELD_NAMES)[number], string> = {
  goal: 'What this session is trying to achieve, in a sentence or two.',
  state: 'Where the work stands right now: done, in flight, blocked.',
  decisions: 'Decisions and rulings made, each with its reason.',
  next_step: 'The very next concrete action on resume.',
  open_questions: 'Questions still waiting on the person.',
  failed_attempts: 'Approaches tried that did not work, and why.',
}

export const INPUT_SCHEMA = {
  type: 'object',
  properties: Object.fromEntries(FIELD_NAMES.map(n => [n, { type: 'string', description: DESCRIBE[n] }])),
  required: [...REQUIRED],
} as const

export const TOOL_DESCRIPTION =
  'Save a handover for this session so work can resume after the context is cleared. ' +
  'Call it only when context-vigil-mod asks you to. Write for a fresh reader who knows nothing of this conversation.'

export function parseFields(input: Record<string, unknown>): { ok: true; fields: Fields } | { ok: false; error: string } {
  const out: Record<string, string> = {}
  for (const name of FIELD_NAMES) {
    const v = input[name]
    if (v === undefined || v === null) { out[name] = ''; continue }
    if (typeof v !== 'string') return { ok: false, error: `${name} must be a string` }
    out[name] = v.trim()
  }
  for (const name of REQUIRED) if (!out[name]) return { ok: false, error: `${name} is required and must not be blank` }
  return { ok: true, fields: out as Fields }
}

const TITLES: Record<(typeof FIELD_NAMES)[number], string> = {
  goal: 'Goal', state: 'State', decisions: 'Decisions', next_step: 'Next step',
  open_questions: 'Open questions', failed_attempts: 'Failed attempts',
}

export function renderHandover(f: Fields, s: Snapshot): string {
  const parts = [`# 📜 Handover — ${s.session} (${s.at})`, '']
  for (const name of FIELD_NAMES) {
    if (!f[name]) continue
    parts.push(`## ${TITLES[name]}`, '', f[name], '')
  }
  parts.push('## Snapshot', '',
    `- cwd: ${s.cwd}`,
    `- branch: ${s.branch ?? '(not a git repo)'}`,
    `- context: ${s.contextPct === null ? 'unknown' : `${s.contextPct}%`}`,
    `- dirty: ${s.dirty.length ? s.dirty.join(', ') : 'none'}`,
    `- edited this session: ${s.edited.length ? s.edited.join(', ') : 'none'}`,
    '')
  return parts.join('\n')
}

const WHY: Record<PendingReason, string> = {
  threshold: 'Context is past the handover threshold.',
  request: 'The person asked for a handover.',
  last_light: 'The session has gone idle and the prompt cache is about to go cold. Do not clear; just save the handover.',
  limit: 'A usage limit is close. Save the handover so work can resume after the reset.',
}

export function instructionText(reason: PendingReason): string {
  return `[context-vigil-mod] ${WHY[reason]} Call the ${TOOL_FULL} tool now with a complete handover ` +
    '(goal, state, decisions, next step, open questions, failed attempts). Do nothing else this turn.'
}

export function resumeText(path: string): string {
  return `[context-vigil-mod] Resume from the handover injected above (saved at ${path}). Start with its next step.`
}

export function injectText(markdown: string): string {
  return `[context-vigil-mod] Handover from before the clear:\n\n${markdown}`
}

// After a limit early stop there was no clear: the conversation is still here.
export function limitResumeText(path: string): string {
  return `[context-vigil-mod] The usage limit has reset. Continue the work; the handover you wrote is saved at ${path} if you need it.`
}
```

- [ ] **Step 4: Gates** — clean.

- [ ] **Step 5: Commit**
```bash
git add plugins/context-vigil-mod/core/handover.ts plugins/context-vigil-mod/tests/handover.test.ts
git commit -m "feat(context-vigil-mod): handover core — thresholds, tool schema, render, texts" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Fj6V4wmyLYFK41Ed3YAqf"
```

---

### Task 6: The clear gate (surfaces)

**Files:**
- Create: `plugins/context-vigil-mod/core/surfaces.ts`
- Test: `tests/surfaces.test.ts`

**Interfaces:**
- Consumes: `RcAnswer` from `../types`; `WaitReason` from `../core/voice` (type only).
- Produces: `COUNTDOWN_MS = 30_000`, `HOLDBACK_MS = 120_000`, `RECHECK_MS = 2_000`; `type GateFacts`; `type Gate = { go: true } | { go: false; reason: WaitReason; recheckMs: number | null }`; `clearGate(f: GateFacts): Gate`; `needsRcQuestion(onPhone: boolean, rc: RcAnswer, wouldArm: boolean): boolean`.

- [ ] **Step 1: Write the failing test** `tests/surfaces.test.ts`:
```ts
import { describe, expect, test } from 'claude-code/testing'
import { COUNTDOWN_MS, HOLDBACK_MS, RECHECK_MS, clearGate, needsRcQuestion } from '../core/surfaces'

const base = { now: 1_000_000, draft: '', onPhone: false, lastBridgeAt: null, rcAutoClear: 'unanswered' as const, latched: false, countdownEndsAt: null, classicActive: false, unattended: true }

describe('clearGate', () => {
  test('terminal, empty box: go', () => expect(clearGate(base)).toEqual({ go: true }))
  test('classic active wins over everything', () => {
    expect(clearGate({ ...base, classicActive: true, latched: true })).toEqual({ go: false, reason: 'classic', recheckMs: null })
  })
  test('the latch parks the clear until it lifts', () => {
    expect(clearGate({ ...base, latched: true })).toEqual({ go: false, reason: 'latched', recheckMs: null })
  })
  test('a draft in the terminal box waits and rechecks', () => {
    expect(clearGate({ ...base, draft: 'half a sen' })).toEqual({ go: false, reason: 'draft', recheckMs: RECHECK_MS })
    expect(clearGate({ ...base, draft: '   ' })).toEqual({ go: true })
  })
  describe('on the phone, unattended', () => {
    const phone = { ...base, onPhone: true, lastBridgeAt: 0 }
    test('unanswered or declined never clears', () => {
      expect(clearGate(phone)).toEqual({ go: false, reason: 'rc-unanswered', recheckMs: null })
      expect(clearGate({ ...phone, rcAutoClear: 'no' })).toEqual({ go: false, reason: 'rc-declined', recheckMs: null })
    })
    test('allowed: holdback within 2 min of the last bridge prompt', () => {
      const f = { ...phone, rcAutoClear: 'yes' as const, lastBridgeAt: base.now - 30_000 }
      expect(clearGate(f)).toEqual({ go: false, reason: 'rc-holdback', recheckMs: HOLDBACK_MS - 30_000 })
    })
    test('allowed: then the countdown starts, runs, and lets it go', () => {
      const f = { ...phone, rcAutoClear: 'yes' as const }
      expect(clearGate(f)).toEqual({ go: false, reason: 'countdown-start', recheckMs: COUNTDOWN_MS })
      expect(clearGate({ ...f, countdownEndsAt: base.now + 10_000 })).toEqual({ go: false, reason: 'countdown', recheckMs: 10_000 })
      expect(clearGate({ ...f, countdownEndsAt: base.now })).toEqual({ go: true })
    })
  })
  test('a clear the person asked for from the phone goes straight through', () => {
    expect(clearGate({ ...base, onPhone: true, unattended: false })).toEqual({ go: true })
  })
})

test('needsRcQuestion only when auto mode would arm on the phone with no answer yet', () => {
  expect(needsRcQuestion(true, 'unanswered', true)).toBe(true)
  expect(needsRcQuestion(true, 'no', true)).toBe(false)
  expect(needsRcQuestion(false, 'unanswered', true)).toBe(false)
  expect(needsRcQuestion(true, 'unanswered', false)).toBe(false)
})
```

- [ ] **Step 2: Run to see it fail** — FAIL (module missing).

- [ ] **Step 3: Implement** `core/surfaces.ts`:
```ts
import type { RcAnswer } from '../types'
import type { WaitReason } from './voice'

export const COUNTDOWN_MS = 30_000
export const HOLDBACK_MS = 120_000
export const RECHECK_MS = 2_000

export type GateFacts = {
  now: number
  draft: string
  onPhone: boolean
  lastBridgeAt: number | null
  rcAutoClear: RcAnswer
  latched: boolean
  countdownEndsAt: number | null
  classicActive: boolean
  unattended: boolean
}

export type Gate = { go: true } | { go: false; reason: WaitReason; recheckMs: number | null }

export function clearGate(f: GateFacts): Gate {
  if (f.classicActive) return { go: false, reason: 'classic', recheckMs: null }
  if (f.latched) return { go: false, reason: 'latched', recheckMs: null }
  if (f.draft.trim()) return { go: false, reason: 'draft', recheckMs: RECHECK_MS }
  if (f.onPhone && f.unattended) {
    if (f.rcAutoClear === 'unanswered') return { go: false, reason: 'rc-unanswered', recheckMs: null }
    if (f.rcAutoClear === 'no') return { go: false, reason: 'rc-declined', recheckMs: null }
    if (f.lastBridgeAt !== null && f.now - f.lastBridgeAt < HOLDBACK_MS) {
      return { go: false, reason: 'rc-holdback', recheckMs: HOLDBACK_MS - (f.now - f.lastBridgeAt) }
    }
    if (f.countdownEndsAt === null) return { go: false, reason: 'countdown-start', recheckMs: COUNTDOWN_MS }
    if (f.now < f.countdownEndsAt) return { go: false, reason: 'countdown', recheckMs: f.countdownEndsAt - f.now }
  }
  return { go: true }
}

// Asked when auto mode would first arm in a bridge session (spec §2), not at the first clear.
export function needsRcQuestion(onPhone: boolean, rc: RcAnswer, wouldArm: boolean): boolean {
  return onPhone && wouldArm && rc === 'unanswered'
}
```

- [ ] **Step 4: Gates** — clean.

- [ ] **Step 5: Commit**
```bash
git add plugins/context-vigil-mod/core/surfaces.ts plugins/context-vigil-mod/tests/surfaces.test.ts
git commit -m "feat(context-vigil-mod): clear gate with Remote Control countdown and holdback" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Fj6V4wmyLYFK41Ed3YAqf"
```

---

### Task 7: Last-light core

**Files:**
- Create: `plugins/context-vigil-mod/core/last-light.ts`
- Test: `tests/last-light.test.ts`

**Interfaces:**
- Consumes: `Mode` from `../types`; `classifyOrigin` from `../core/arming`.
- Produces: `LEAD_MS = 300_000`, `TTL_1H = 3_600_000`, `TTL_5M = 300_000`; `ttlFromLabel(label: string): number`; `fireAt(lastApiAt: number, ttlMs: number): number | null`; `type FireFacts`; `shouldFire(f: FireFacts): { fire: true } | { fire: false; reason: 'off' | 'not-idle' | 'small' | 'pending' | 'latched' | 'disarmed' }`; `rearm(prev: boolean, origin: string): boolean`; `holdOnReturn(f: { pendingIsLastLight: boolean; origin: string; now: number; cacheExpiresAt: number | null }): boolean`.

- [ ] **Step 1: Write the failing test** `tests/last-light.test.ts`:
```ts
import { describe, expect, test } from 'claude-code/testing'
import { LEAD_MS, TTL_1H, TTL_5M, fireAt, holdOnReturn, rearm, shouldFire, ttlFromLabel } from '../core/last-light'

test('ttl labels', () => {
  expect(ttlFromLabel('1h')).toBe(TTL_1H)
  expect(ttlFromLabel('5m')).toBe(TTL_5M)
  expect(ttlFromLabel('junk')).toBe(TTL_1H)
})

test('fireAt is last API activity + TTL − lead; inactive on a 5-minute cache', () => {
  expect(fireAt(1000, TTL_1H)).toBe(1000 + TTL_1H - LEAD_MS)
  expect(fireAt(1000, TTL_5M)).toBe(null)
})

describe('shouldFire', () => {
  const ok = { enabled: true, mode: 'idle' as const, contextPct: 30, threshold: 25, pending: false, latched: false, armed: true }
  test('fires when every condition holds', () => expect(shouldFire(ok)).toEqual({ fire: true }))
  test('each condition blocks with its reason', () => {
    expect(shouldFire({ ...ok, enabled: false })).toEqual({ fire: false, reason: 'off' })
    expect(shouldFire({ ...ok, mode: 'attended' })).toEqual({ fire: false, reason: 'not-idle' })
    expect(shouldFire({ ...ok, mode: 'auto' })).toEqual({ fire: false, reason: 'not-idle' })
    expect(shouldFire({ ...ok, contextPct: 24 })).toEqual({ fire: false, reason: 'small' })
    expect(shouldFire({ ...ok, contextPct: null })).toEqual({ fire: false, reason: 'small' })
    expect(shouldFire({ ...ok, pending: true })).toEqual({ fire: false, reason: 'pending' })
    expect(shouldFire({ ...ok, latched: true })).toEqual({ fire: false, reason: 'latched' })
    expect(shouldFire({ ...ok, armed: false })).toEqual({ fire: false, reason: 'disarmed' })
  })
})

test('loop guard: only a human prompt re-arms', () => {
  expect(rearm(false, 'composer')).toBe(true)
  expect(rearm(false, 'bridge')).toBe(true)
  expect(rearm(false, 'plugin')).toBe(false)
  expect(rearm(false, 'scheduled-trigger')).toBe(false)
  expect(rearm(true, 'plugin')).toBe(true)
})

describe('holdOnReturn', () => {
  const f = { pendingIsLastLight: true, origin: 'composer', now: 10, cacheExpiresAt: 5 }
  test('a human prompt after expiry with a last-light handover pending is held', () => expect(holdOnReturn(f)).toBe(true))
  test('not before expiry, not for agent prompts, not without a last-light handover', () => {
    expect(holdOnReturn({ ...f, now: 4 })).toBe(false)
    expect(holdOnReturn({ ...f, origin: 'plugin' })).toBe(false)
    expect(holdOnReturn({ ...f, pendingIsLastLight: false })).toBe(false)
    expect(holdOnReturn({ ...f, cacheExpiresAt: null })).toBe(false)
  })
})
```

- [ ] **Step 2: Run to see it fail** — FAIL.

- [ ] **Step 3: Implement** `core/last-light.ts`:
```ts
import type { Mode } from '../types'
import { classifyOrigin } from './arming'

export const LEAD_MS = 300_000
export const TTL_1H = 3_600_000
export const TTL_5M = 300_000

export function ttlFromLabel(label: string): number {
  return label === '5m' ? TTL_5M : TTL_1H
}

export function fireAt(lastApiAt: number, ttlMs: number): number | null {
  if (ttlMs < TTL_1H) return null
  return lastApiAt + ttlMs - LEAD_MS
}

export type FireFacts = {
  enabled: boolean
  mode: Mode
  contextPct: number | null
  threshold: number
  pending: boolean
  latched: boolean
  armed: boolean
}

export function shouldFire(f: FireFacts):
  { fire: true } | { fire: false; reason: 'off' | 'not-idle' | 'small' | 'pending' | 'latched' | 'disarmed' } {
  if (!f.enabled) return { fire: false, reason: 'off' }
  if (f.mode !== 'idle') return { fire: false, reason: 'not-idle' }
  if (f.contextPct === null || f.contextPct < f.threshold) return { fire: false, reason: 'small' }
  if (f.pending) return { fire: false, reason: 'pending' }
  if (f.latched) return { fire: false, reason: 'latched' }
  if (!f.armed) return { fire: false, reason: 'disarmed' }
  return { fire: true }
}

export function rearm(prev: boolean, origin: string): boolean {
  return classifyOrigin(origin) === 'human' ? true : prev
}

export function holdOnReturn(f: { pendingIsLastLight: boolean; origin: string; now: number; cacheExpiresAt: number | null }): boolean {
  return f.pendingIsLastLight && classifyOrigin(f.origin) === 'human' && f.cacheExpiresAt !== null && f.now >= f.cacheExpiresAt
}
```

- [ ] **Step 4: Gates** — clean.

- [ ] **Step 5: Commit**
```bash
git add plugins/context-vigil-mod/core/last-light.ts plugins/context-vigil-mod/tests/last-light.test.ts
git commit -m "feat(context-vigil-mod): last-light core — timer, fire conditions, loop guard, return hold" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Fj6V4wmyLYFK41Ed3YAqf"
```

---

### Task 8: Limits core

**Files:**
- Create: `plugins/context-vigil-mod/core/limits.ts`
- Test: `tests/limits.test.ts`

**Interfaces:**
- Consumes: `Latch`, `RateLimit`, `Settings` from `../types`.
- Produces: `latchFromStopFailure(error: string, limits: RateLimit[], now: number): Latch`; `latchFromMeasure(limits: RateLimit[]): Latch`; `latchCleared(l: Latch, now: number, limits: RateLimit[]): boolean`; `earlyStopDue(limits, s: Pick<Settings,'limits'|'limitPct'|'limitWindows'>, fired: string[]): { kind: string; key: string; pct: number; resetsAtMs: number } | null`; `RESUME_DELAY_MS = 300_000`; `HOP_MS = 3_600_000`; `nextHop(now: number, resumeAt: number): number`; `formatHHMM(ms: number): string`.

- [ ] **Step 1: Write the failing test** `tests/limits.test.ts`:
```ts
import { describe, expect, test } from 'claude-code/testing'
import { HOP_MS, earlyStopDue, formatHHMM, latchCleared, latchFromMeasure, latchFromStopFailure, nextHop } from '../core/limits'

const T = Date.UTC(2026, 9, 4, 12)
const iso = (ms: number) => new Date(ms).toISOString()

describe('latch', () => {
  test('a rate_limit StopFailure latches on the fullest window', () => {
    const l = latchFromStopFailure('rate_limit', [
      { kind: 'five_hour', percentUsed: 100, resetsAt: iso(T + 3600_000) },
      { kind: 'seven_day', percentUsed: 60, resetsAt: iso(T + 86400_000) },
    ], T)
    expect(l).toEqual({ kind: 'five_hour', resetsAtMs: T + 3600_000 })
  })
  test('other errors never latch', () => expect(latchFromStopFailure('overloaded', [], T)).toBe(null))
  test('rate_limit with no window known latches for an hour', () => {
    expect(latchFromStopFailure('rate_limit', [], T)).toEqual({ kind: 'unknown', resetsAtMs: T + 3600_000 })
  })
  test('a measure at or past 100% latches', () => {
    expect(latchFromMeasure([{ kind: 'seven_day', percentUsed: 100, resetsAt: iso(T + 5) }])).toEqual({ kind: 'seven_day', resetsAtMs: T + 5 })
    expect(latchFromMeasure([{ kind: 'seven_day', percentUsed: 99.9, resetsAt: iso(T + 5) }])).toBe(null)
  })
  test('the latch clears at resetsAt or when its window drops', () => {
    const l = { kind: 'five_hour', resetsAtMs: T + 100 }
    expect(latchCleared(l, T, [{ kind: 'five_hour', percentUsed: 100 }])).toBe(false)
    expect(latchCleared(l, T + 100, [])).toBe(true)
    expect(latchCleared(l, T, [{ kind: 'five_hour', percentUsed: 3 }])).toBe(true)
    expect(latchCleared(null, T, [])).toBe(false)
  })
})

describe('earlyStopDue', () => {
  const s = { limits: true, limitPct: 95, limitWindows: ['seven_day' as const, 'spend_limit' as const] }
  const seven = { kind: 'seven_day', percentUsed: 96, resetsAt: iso(T + 1000) }
  test('a watched window at the trigger is due once per window', () => {
    const due = earlyStopDue([seven], s, [])
    expect(due).toEqual({ kind: 'seven_day', key: `seven_day:${iso(T + 1000)}`, pct: 96, resetsAtMs: T + 1000 })
    expect(earlyStopDue([seven], s, [due?.key ?? ''])).toBe(null)
  })
  test('five_hour is never watched; unwatched windows are ignored', () => {
    expect(earlyStopDue([{ kind: 'five_hour', percentUsed: 99, resetsAt: iso(T) }], s, [])).toBe(null)
    expect(earlyStopDue([seven], { ...s, limitWindows: ['spend_limit'] }, [])).toBe(null)
  })
  test('limits off or below the trigger: nothing', () => {
    expect(earlyStopDue([seven], { ...s, limits: false }, [])).toBe(null)
    expect(earlyStopDue([seven], { ...s, limitPct: 98 }, [])).toBe(null)
  })
  test('a window with no resetsAt cannot be keyed and is skipped', () => {
    expect(earlyStopDue([{ kind: 'seven_day', percentUsed: 99 }], s, [])).toBe(null)
  })
})

test('nextHop waits in ≤ 1 h hops and hits 0 at the resume time', () => {
  expect(nextHop(0, 5 * HOP_MS)).toBe(HOP_MS)
  expect(nextHop(0, 1000)).toBe(1000)
  expect(nextHop(1000, 1000)).toBe(0)
  expect(nextHop(2000, 1000)).toBe(0)
})

test('formatHHMM is local hours and minutes', () => {
  expect(formatHHMM(new Date(2026, 9, 4, 14, 5).getTime())).toBe('14:05')
  expect(formatHHMM(new Date(2026, 9, 4, 9, 0).getTime())).toBe('09:00')
})
```

- [ ] **Step 2: Run to see it fail** — FAIL.

- [ ] **Step 3: Implement** `core/limits.ts`:
```ts
import type { Latch, RateLimit, Settings } from '../types'

const resetMs = (l: RateLimit): number | null => {
  if (!l.resetsAt) return null
  const ms = Date.parse(l.resetsAt)
  return Number.isFinite(ms) ? ms : null
}

export function latchFromStopFailure(error: string, limits: RateLimit[], now: number): Latch {
  if (error !== 'rate_limit') return null
  const known = limits.filter(l => resetMs(l) !== null).sort((a, b) => b.percentUsed - a.percentUsed)
  const top = known[0]
  if (!top) return { kind: 'unknown', resetsAtMs: now + 3_600_000 }
  return { kind: top.kind, resetsAtMs: resetMs(top) as number }
}

export function latchFromMeasure(limits: RateLimit[]): Latch {
  const full = limits.filter(l => l.percentUsed >= 100 && resetMs(l) !== null)
  if (!full.length) return null
  const last = full.reduce((a, b) => ((resetMs(a) as number) >= (resetMs(b) as number) ? a : b))
  return { kind: last.kind, resetsAtMs: resetMs(last) as number }
}

export function latchCleared(l: Latch, now: number, limits: RateLimit[]): boolean {
  if (!l) return false
  if (now >= l.resetsAtMs) return true
  const same = limits.find(x => x.kind === l.kind)
  return same !== undefined && same.percentUsed < 100
}

export function earlyStopDue(
  limits: RateLimit[], s: Pick<Settings, 'limits' | 'limitPct' | 'limitWindows'>, fired: string[],
): { kind: string; key: string; pct: number; resetsAtMs: number } | null {
  if (!s.limits) return null
  for (const l of limits) {
    if (!(s.limitWindows as string[]).includes(l.kind)) continue
    if (l.percentUsed < s.limitPct) continue
    const ms = resetMs(l)
    if (ms === null || !l.resetsAt) continue
    const key = `${l.kind}:${l.resetsAt}`
    if (fired.includes(key)) continue
    return { kind: l.kind, key, pct: l.percentUsed, resetsAtMs: ms }
  }
  return null
}

export const RESUME_DELAY_MS = 300_000
export const HOP_MS = 3_600_000

export function nextHop(now: number, resumeAt: number): number {
  return Math.max(0, Math.min(HOP_MS, resumeAt - now))
}

export function formatHHMM(ms: number): string {
  const d = new Date(ms)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
```

- [ ] **Step 4: Gates** — clean.

- [ ] **Step 5: Commit**
```bash
git add plugins/context-vigil-mod/core/limits.ts plugins/context-vigil-mod/tests/limits.test.ts
git commit -m "feat(context-vigil-mod): limits core — latch, configurable early stop, resume hops" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Fj6V4wmyLYFK41Ed3YAqf"
```

---

### Task 9: Setup core — steps, cards, answers, "Tell me more"

**Files:**
- Create: `plugins/context-vigil-mod/core/setup.ts`
- Test: `tests/setup.test.ts`

**Interfaces:**
- Consumes: `Settings`, `StepId`, `Window` from `../types`.
- Produces: `TELL = 'Tell me more'`; `type Question = { header: string; question: string; multiSelect: boolean; options: { label: string; description: string }[] }`; `STEPS: Record<StepId, Step>`; `FLOW: StepId[]`; `ALIASES: Record<string, StepId[]>`; `questionFor(id: StepId, explain?: boolean): Question`; `nextCard(s: Settings, asked: StepId[], only?: string): StepId[]` (never a dependant beside its parent; ≤ 4); `isStep(alias: string): boolean`; `extractAnswers(input: unknown, result: unknown): Record<string, string>`; `stepForQuestion(text: string): StepId | undefined`; `applyAnswers(s: Settings, pairs: { step: StepId; answer: string }[]): { settings: Settings; retell: StepId[] }`.

- [ ] **Step 1: Write the failing test** `tests/setup.test.ts`:
```ts
import { describe, expect, test } from 'claude-code/testing'
import { DEFAULTS } from '../core/settings'
import { ALIASES, FLOW, STEPS, TELL, applyAnswers, extractAnswers, isStep, nextCard, questionFor, stepForQuestion } from '../core/setup'
import type { StepId } from '../types'

const ALL = Object.keys(STEPS) as StepId[]

describe('cards fit AskUserQuestion', () => {
  test('headers ≤ 12 UTF-16 units; 2–4 options including Tell me more', () => {
    for (const id of ALL) {
      const q = questionFor(id)
      expect(q.header.length).toBeLessThanOrEqual(12)
      expect(q.options.length).toBeGreaterThanOrEqual(2)
      expect(q.options.length).toBeLessThanOrEqual(4)
      expect(q.options.at(-1)?.label).toBe(TELL)
      expect(q.question.endsWith('?')).toBe(true)
    }
  })
  test('Tell me more re-asks the same question with the explanation first', () => {
    const q = questionFor('bar', true)
    expect(q.question.startsWith(STEPS.bar.explain)).toBe(true)
    expect(q.question.endsWith(STEPS.bar.question)).toBe(true)
    expect(stepForQuestion(q.question)).toBe('bar')
    expect(stepForQuestion(STEPS.bar.question)).toBe('bar')
    expect(stepForQuestion('something else?')).toBe(undefined)
  })
  test('windows is multi-select', () => expect(questionFor('limit_windows').multiSelect).toBe(true))
})

describe('nextCard', () => {
  test('defaults: card 1 skips steps whose parent is off', () => {
    expect(nextCard(DEFAULTS, [])).toEqual(['nudge', 'bar', 'auto', 'last_light'])
  })
  test('card 2 picks up follow-ups the answers switched on, never a dependant beside its parent', () => {
    const s = { ...DEFAULTS, auto: true, lastLight: true }
    expect(nextCard(s, ['nudge', 'bar', 'auto', 'last_light'])).toEqual(['idle', 'last_light_at', 'limits'])
  })
  test('card 3 asks the limits follow-ups only after limits was answered On', () => {
    const asked = ['nudge', 'bar', 'auto', 'last_light', 'idle', 'last_light_at', 'limits'] as StepId[]
    expect(nextCard(DEFAULTS, asked)).toEqual(['limit_pct', 'limit_windows'])
    expect(nextCard({ ...DEFAULTS, limits: false }, asked)).toEqual([])
  })
  test('done when nothing is left', () => {
    expect(nextCard(DEFAULTS, [...FLOW])).toEqual([])
  })
  test('one step by alias; dependants follow in the next card', () => {
    expect(nextCard(DEFAULTS, [], 'bar')).toEqual(['bar'])
    expect(nextCard(DEFAULTS, [], 'limits')).toEqual(['limits'])
    expect(nextCard(DEFAULTS, ['limits'], 'limits')).toEqual(['limit_pct', 'limit_windows'])
    expect(nextCard({ ...DEFAULTS, auto: false }, [], 'auto')).toEqual(['auto'])
    expect(nextCard({ ...DEFAULTS, auto: false }, ['auto'], 'auto')).toEqual([])
    expect(nextCard(DEFAULTS, [], 'rc')).toEqual(['rc'])
    expect(nextCard(DEFAULTS, [], 'bogus')).toEqual([])
    expect(ALIASES['last-light']).toEqual(['last_light', 'last_light_at'])
  })
  test('isStep tells a known alias from a typo', () => {
    expect(isStep('limits')).toBe(true)
    expect(isStep('bogus')).toBe(false)
  })
})

describe('extractAnswers', () => {
  test('answers on the tool input win', () => {
    expect(extractAnswers({ answers: { 'Q?': 'A' } }, { result: { answers: { 'Q?': 'B' } } })).toEqual({ 'Q?': 'A' })
  })
  test('else answers on the tool result', () => {
    expect(extractAnswers({}, { result: { questions: [], answers: { 'Q?': 'B' } } })).toEqual({ 'Q?': 'B' })
  })
  test('non-string answers are dropped; nothing found is empty', () => {
    expect(extractAnswers({ answers: { 'Q?': 3, 'R?': 'x' } }, undefined)).toEqual({ 'R?': 'x' })
    expect(extractAnswers(null, { deny: 'dismissed' })).toEqual({})
  })
})

describe('applyAnswers', () => {
  test('labels apply', () => {
    const r = applyAnswers(DEFAULTS, [
      { step: 'nudge', answer: '25%' }, { step: 'bar', answer: 'Off' }, { step: 'auto', answer: 'On' }, { step: 'idle', answer: '60 min' },
      { step: 'last_light', answer: 'On' }, { step: 'last_light_at', answer: '50%' }, { step: 'limits', answer: 'Off' }, { step: 'rc', answer: 'Yes' },
    ])
    expect(r.retell).toEqual([])
    expect(r.settings).toEqual({ ...DEFAULTS, nudgeAt: 25, bar: false, auto: true, idleMin: 60, lastLight: true, lastLightAt: 50, limits: false, rcAutoClear: 'yes' })
  })
  test('Tell me more is collected for a retell and changes nothing', () => {
    const r = applyAnswers(DEFAULTS, [{ step: 'bar', answer: TELL }, { step: 'nudge', answer: '50%' }])
    expect(r.retell).toEqual(['bar'])
    expect(r.settings).toEqual({ ...DEFAULTS, nudgeAt: 50 })
  })
  test('trigger % takes Other as a number 1–100', () => {
    expect(applyAnswers(DEFAULTS, [{ step: 'limit_pct', answer: '97' }]).settings.limitPct).toBe(97)
    expect(applyAnswers(DEFAULTS, [{ step: 'limit_pct', answer: '95% (Recommended)' }]).settings.limitPct).toBe(95)
    const bad = applyAnswers(DEFAULTS, [{ step: 'limit_pct', answer: 'lots' }])
    expect(bad.retell).toEqual(['limit_pct'])
    expect(bad.settings.limitPct).toBe(95)
  })
  test('windows multi-select, comma-joined, any order, may be empty', () => {
    expect(applyAnswers(DEFAULTS, [{ step: 'limit_windows', answer: 'spend_limit' }]).settings.limitWindows).toEqual(['spend_limit'])
    expect(applyAnswers(DEFAULTS, [{ step: 'limit_windows', answer: 'spend_limit, seven_day' }]).settings.limitWindows).toEqual(['seven_day', 'spend_limit'])
    expect(applyAnswers(DEFAULTS, [{ step: 'limit_windows', answer: `seven_day, ${TELL}` }]).retell).toEqual(['limit_windows'])
  })
  test('an unknown label is retold', () => {
    expect(applyAnswers(DEFAULTS, [{ step: 'bar', answer: 'Maybe' }]).retell).toEqual(['bar'])
  })
})
```

- [ ] **Step 2: Run to see it fail** — FAIL.

- [ ] **Step 3: Implement** `core/setup.ts`:
```ts
import type { Settings, StepId, Window } from '../types'

export const TELL = 'Tell me more'

export type Question = {
  header: string
  question: string
  multiSelect: boolean
  options: { label: string; description: string }[]
}

type Opt = { label: string; description: string; apply: (s: Settings) => Settings }
type Step = {
  header: string
  question: string
  explain: string
  options: Opt[]
  multiSelect?: true
  other?: (s: Settings, text: string) => Settings | null
  askIf: (s: Settings) => boolean
}

const pctOpts = (key: 'nudgeAt' | 'lastLightAt', values: number[], rec: number): Opt[] =>
  values.map(n => ({ label: `${n}%`, description: n === rec ? 'Recommended' : '', apply: s => ({ ...s, [key]: n }) }))
const onOff = (key: 'bar' | 'auto' | 'lastLight' | 'limits', recommendOn: boolean, onFirst: boolean): Opt[] => {
  const on: Opt = { label: 'On', description: recommendOn ? 'Recommended' : '', apply: s => ({ ...s, [key]: true }) }
  const off: Opt = { label: 'Off', description: recommendOn ? '' : 'Recommended', apply: s => ({ ...s, [key]: false }) }
  return onFirst ? [on, off] : [off, on]
}
const always = () => true

export const STEPS: Record<StepId, Step> = {
  nudge: {
    header: '🎚️ Nudge at', question: 'At what context % should I nudge you to hand over?',
    explain: 'When context crosses this level you get the vigil bar in the terminal (or a notice on the phone), and again every +5%. Lower means earlier, smaller handovers. Default 35%.',
    options: pctOpts('nudgeAt', [25, 35, 50], 35), askIf: always,
  },
  bar: {
    header: '🎛️Vigil bar', question: 'Show the vigil bar above the prompt at the threshold?',
    explain: 'A one-line bar: 1 hand over · 2 remind me at +5% · 0 dismiss. A bare digit typed into an empty prompt presses it, so it only shows from the threshold until you choose. Off means notices only. Default On.',
    options: onOff('bar', true, true), askIf: always,
  },
  auto: {
    header: '🤖 Auto mode', question: 'Let me hand over, clear and resume by myself while you are away?',
    explain: 'Auto mode arms only when you have sent nothing for the idle window and the agent is still working on its own; any message from you disarms it at once. Default Off.',
    options: onOff('auto', false, false), askIf: always,
  },
  idle: {
    header: '⏱️Idle time', question: 'How long without a message from you before auto mode may arm?',
    explain: 'Messages, slash commands and typing in the terminal all count as you being here. Pick longer if you jump between windows a lot. Default 30 min.',
    options: [15, 30, 60].map(n => ({ label: `${n} min`, description: n === 30 ? 'Recommended' : '', apply: (s: Settings) => ({ ...s, idleMin: n }) })),
    askIf: s => s.auto,
  },
  last_light: {
    header: '🌅Last light', question: 'Write a handover before an idle 1-hour cache goes cold?',
    explain: 'When you and the agent are both idle, a few minutes before the prompt cache expires I write a handover — nothing is cleared. When you come back I ask: resume from it cheaply, or carry on and pay the cold cache. Default Off.',
    options: onOff('lastLight', false, false), askIf: always,
  },
  last_light_at: {
    header: '🌅 Threshold', question: 'At what context % should last light step in?',
    explain: 'Below this, a cold cache is cheap enough not to bother. Default 25%.',
    options: pctOpts('lastLightAt', [25, 35, 50], 25), askIf: s => s.lastLight,
  },
  limits: {
    header: '⏳ Limits', question: 'Stop early and hand over before a 7-day or spend limit runs out?',
    explain: 'Near the limit I write a handover and arrange to resume after the reset if this session stays open. The 5-hour limit is left to Claude Code\'s own wrap-up and auto-continue. Default On.',
    options: onOff('limits', true, true), askIf: always,
  },
  limit_pct: {
    header: '⏳ Trigger %', question: 'At what % of the limit should I stop early?',
    explain: 'Higher squeezes more work in; lower leaves more room for the handover itself. Type any whole number under Other. Default 95%.',
    options: [90, 95, 98].map(n => ({ label: n === 95 ? '95% (Recommended)' : `${n}%`, description: '', apply: (s: Settings) => ({ ...s, limitPct: n }) })),
    other: (s, text) => {
      const n = Number.parseInt(text, 10)
      return Number.isFinite(n) && n >= 1 && n <= 100 ? { ...s, limitPct: n } : null
    },
    askIf: s => s.limits,
  },
  limit_windows: {
    header: '⏳ Windows', question: 'Which limits should I watch?',
    explain: 'seven_day is the weekly window; spend_limit is a gateway or monthly spend cap. Pick either or both. Default both.',
    options: (['seven_day', 'spend_limit'] as Window[]).map(w => ({ label: w, description: '', apply: (s: Settings) => s })),
    multiSelect: true, askIf: s => s.limits,
  },
  rc: {
    header: '📱 RC clear', question: 'Allow auto-clear in Remote Control (phone) sessions?',
    explain: 'Your phone\'s typing is invisible to me, so a clear could land while you write. With Yes, a 30-second countdown runs first (send anything to cancel) and I never clear within 2 minutes of your last phone message. Default No.',
    options: [
      { label: 'No', description: 'Recommended', apply: s => ({ ...s, rcAutoClear: 'no' }) },
      { label: 'Yes', description: 'With countdown and holdback', apply: s => ({ ...s, rcAutoClear: 'yes' }) },
    ],
    askIf: () => false,
  },
}

export const FLOW: StepId[] = ['nudge', 'bar', 'auto', 'idle', 'last_light', 'last_light_at', 'limits', 'limit_pct', 'limit_windows']

export const ALIASES: Record<string, StepId[]> = {
  nudge: ['nudge'], bar: ['bar'], auto: ['auto', 'idle'], 'last-light': ['last_light', 'last_light_at'],
  limits: ['limits', 'limit_pct', 'limit_windows'], rc: ['rc'],
}

export function questionFor(id: StepId, explain = false): Question {
  const st = STEPS[id]
  return {
    header: st.header,
    question: explain ? `${st.explain}\n\n${st.question}` : st.question,
    multiSelect: st.multiSelect === true,
    options: [...st.options.map(o => ({ label: o.label, description: o.description })), { label: TELL, description: 'Explain this step, then ask again' }],
  }
}

// A dependant is never asked in the same card as its parent: the parent's answer decides it.
const PARENT: Partial<Record<StepId, StepId>> = {
  idle: 'auto', last_light_at: 'last_light', limit_pct: 'limits', limit_windows: 'limits',
}

export function isStep(alias: string): boolean {
  return alias in ALIASES
}

export function nextCard(s: Settings, asked: StepId[], only?: string): StepId[] {
  const pool = only === undefined ? FLOW : (ALIASES[only] ?? [])
  const explicit = only !== undefined
  const card: StepId[] = []
  for (const id of pool) {
    if (card.length === 4) break
    if (asked.includes(id)) continue
    if (!(STEPS[id].askIf(s) || (explicit && (id === 'rc' || pool[0] === id)))) continue
    const parent = PARENT[id]
    if (parent !== undefined && card.includes(parent)) continue
    card.push(id)
  }
  return card
}

// AskUserQuestion answers: on the tool input (answers collected by the permission
// component) or on the result ({ questions, answers }). PROBES.md §3 says which.
export function extractAnswers(input: unknown, result: unknown): Record<string, string> {
  const pick = (v: unknown): Record<string, string> | null => {
    if (!v || typeof v !== 'object') return null
    const out: Record<string, string> = {}
    for (const [k, a] of Object.entries(v as Record<string, unknown>)) if (typeof a === 'string') out[k] = a
    return Object.keys(out).length ? out : null
  }
  const fromInput = pick((input as { answers?: unknown } | null)?.answers)
  if (fromInput) return fromInput
  const res = (result as { result?: { answers?: unknown } } | null | undefined)?.result
  return pick(res?.answers) ?? {}
}

export function stepForQuestion(text: string): StepId | undefined {
  return (Object.keys(STEPS) as StepId[]).find(id => text === STEPS[id].question || text.endsWith(`\n\n${STEPS[id].question}`))
}

export function applyAnswers(s: Settings, pairs: { step: StepId; answer: string }[]): { settings: Settings; retell: StepId[] } {
  let out: Settings = { ...s, limitWindows: [...s.limitWindows] }
  const retell: StepId[] = []
  for (const { step, answer } of pairs) {
    const st = STEPS[step]
    if (st.multiSelect) {
      const picked = answer.split(',').map(x => x.trim()).filter(Boolean)
      if (picked.includes(TELL)) { retell.push(step); continue }
      const order: Window[] = ['seven_day', 'spend_limit']
      out = { ...out, limitWindows: order.filter(w => picked.includes(w)) }
      continue
    }
    if (answer === TELL) { retell.push(step); continue }
    const opt = st.options.find(o => o.label === answer)
    if (opt) { out = opt.apply(out); continue }
    const viaOther = st.other?.(out, answer) ?? null
    if (viaOther) { out = viaOther; continue }
    retell.push(step)
  }
  return { settings: out, retell }
}
```

- [ ] **Step 4: Gates** — clean.

- [ ] **Step 5: Commit**
```bash
git add plugins/context-vigil-mod/core/setup.ts plugins/context-vigil-mod/tests/setup.test.ts
git commit -m "feat(context-vigil-mod): setup steps — options plus Tell me more, cards, answers" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Fj6V4wmyLYFK41Ed3YAqf"
```

---

### Task 10: Git and interlock cores

**Files:**
- Create: `plugins/context-vigil-mod/core/git.ts`, `core/interlock.ts`
- Test: `tests/git.test.ts`, `tests/interlock.test.ts`

**Interfaces:**
- Consumes: `Git` from `../types`.
- Produces: `GIT_ARGV = { branch, status }`; `COALESCE_MS = 1500`; `type RunOut = { exitCode: number; stdout: string }`; `parseGit(branch: RunOut, status: RunOut): Git`; `touchesGit(tool: string): boolean`; `watchPaths(root: string): string[]`; `classicHooksInstalled(settingsText: string | null): boolean`.

- [ ] **Step 1: Write the failing tests**

`tests/git.test.ts`:
```ts
import { expect, test } from 'claude-code/testing'
import { GIT_ARGV, parseGit, touchesGit, watchPaths } from '../core/git'

const ok = (stdout: string) => ({ exitCode: 0, stdout })
const fail = { exitCode: 128, stdout: '' }

test('argv: two git questions, branch and status', () => {
  expect(Object.keys(GIT_ARGV)).toEqual(['branch', 'status'])
  expect(GIT_ARGV.branch).toEqual(['git', 'symbolic-ref', '--short', 'HEAD'])
  expect(GIT_ARGV.status).toEqual(['git', 'status', '--porcelain'])
})
test('parse: branch and tracked changes only', () => {
  expect(parseGit(ok('main\n'), ok(' M a.ts\nA  b.ts\n?? new.ts\n'))).toEqual({ branch: 'main', dirty: ['a.ts', 'b.ts'] })
})
test('parse: failures are unknowns, not crashes', () => {
  expect(parseGit(fail, fail)).toEqual({ branch: null, dirty: [] })
  expect(parseGit(ok('main'), ok(''))).toEqual({ branch: 'main', dirty: [] })
})
test('tools that can change git', () => {
  for (const t of ['Edit', 'Write', 'NotebookEdit', 'Bash']) expect(touchesGit(t)).toBe(true)
  for (const t of ['Read', 'Grep', 'Glob', 'mcp__x__y']) expect(touchesGit(t)).toBe(false)
})
test('watch paths', () => expect(watchPaths('/repo')).toEqual(['/repo/.git/HEAD', '/repo/.git/index']))
```
`tests/interlock.test.ts`:
```ts
import { expect, test } from 'claude-code/testing'
import { classicHooksInstalled } from '../core/interlock'

const settings = (cmd: string) => JSON.stringify({ hooks: { Stop: [{ hooks: [{ type: 'command', command: cmd }] }] } })
// The same fixture string is used by tests/context_vigil_mod/test_install.py (Task 16).
const CLASSIC_CMD = '"/s/context-vigil/scripts/context-vigil" hook stop'

test('classic hook commands are detected', () => {
  expect(classicHooksInstalled(settings(CLASSIC_CMD))).toBe(true)
  expect(classicHooksInstalled(settings('"/u/skills/context-vigil/scripts/context-vigil" hook user-prompt-submit'))).toBe(true)
})
test('other hooks, our own name, no file and junk are not classic', () => {
  expect(classicHooksInstalled(settings('python3 ~/.claude-personal/census/five-hour-guard.py'))).toBe(false)
  expect(classicHooksInstalled(settings('"/x/plugins/context-vigil-mod/scripts/context-vigil-mod" hook stop'))).toBe(false)
  expect(classicHooksInstalled(null)).toBe(false)
  expect(classicHooksInstalled('{not json')).toBe(false)
  expect(classicHooksInstalled(JSON.stringify({ hooks: 'odd' }))).toBe(false)
})
```

- [ ] **Step 2: Run to see them fail** — FAIL.

- [ ] **Step 3: Implement**

`core/git.ts`:
```ts
import type { Git } from '../types'

// Two questions only: `ahead` was dropped while the status-line band is parked (pre-flight F30).
export const GIT_ARGV = {
  branch: ['git', 'symbolic-ref', '--short', 'HEAD'],
  status: ['git', 'status', '--porcelain'],
} as const

export const COALESCE_MS = 1500

export type RunOut = { exitCode: number; stdout: string }

export function parseGit(branch: RunOut, status: RunOut): Git {
  const b = branch.exitCode === 0 ? branch.stdout.trim() || null : null
  const dirty = status.exitCode === 0
    ? status.stdout.split('\n').filter(l => l.length > 3 && !l.startsWith('??')).map(l => l.slice(3))
    : []
  return { branch: b, dirty }
}

const TOUCH = new Set(['Edit', 'Write', 'NotebookEdit', 'Bash'])
export function touchesGit(tool: string): boolean {
  return TOUCH.has(tool)
}

export function watchPaths(root: string): string[] {
  return [`${root}/.git/HEAD`, `${root}/.git/index`]
}
```
`core/interlock.ts`:
```ts
// TEMPORARY: exists only for the side-by-side run with classic context-vigil.
// Removed (with classicSessionPath in name.ts) when classic retires — spec §7.
// Keep in step with the grep -E pattern in scripts/install.sh (same match, bash form).
const CLASSIC = /\/scripts\/context-vigil"\s+hook\s/

export function classicHooksInstalled(settingsText: string | null): boolean {
  if (!settingsText) return false
  let data: unknown
  try { data = JSON.parse(settingsText) } catch { return false }
  const hooks = (data as { hooks?: unknown })?.hooks
  if (!hooks || typeof hooks !== 'object') return false
  for (const entries of Object.values(hooks as Record<string, unknown>)) {
    if (!Array.isArray(entries)) continue
    for (const entry of entries) {
      const list = (entry as { hooks?: unknown })?.hooks
      if (!Array.isArray(list)) continue
      for (const h of list) {
        const cmd = (h as { command?: unknown })?.command
        if (typeof cmd === 'string' && CLASSIC.test(cmd)) return true
      }
    }
  }
  return false
}
```

- [ ] **Step 4: Gates** — clean.

- [ ] **Step 5: Commit**
```bash
git add plugins/context-vigil-mod/core/git.ts plugins/context-vigil-mod/core/interlock.ts plugins/context-vigil-mod/tests/git.test.ts plugins/context-vigil-mod/tests/interlock.test.ts
git commit -m "feat(context-vigil-mod): git parse and staleness; temporary classic interlock" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Fj6V4wmyLYFK41Ed3YAqf"
```

---

### Task 11: Shell foundation — world, logging, notices, arming, git, interlock, registration

Serial from here: Tasks 11–15 all edit `hooks/register.tsx`. Read `PROBES.md` (Task 2) first: §1 decides `notify()`, §2 the tool result shape.

**Files:**
- Modify: `plugins/context-vigil-mod/hooks/register.tsx` (replace the empty shell)
- Create: `plugins/context-vigil-mod/tests/world.tsx`
- Test: `tests/shell-foundation.test.tsx`

**Interfaces:**
- Consumes: everything from Tasks 1, 3, 4, 10, and `INPUT_SCHEMA`, `TOOL_DESCRIPTION` from Task 5.
- Produces (top-level functions in `register.tsx`, used by Tasks 12–15): `log($, kind, fields)`, `notify($, text)`, `submitSoon($, text, delayMs?)`, `observe($, signal)` (also treats a non-empty terminal draft as engagement), `scheduleGit($)`, `nowMs($)`, `bindSession($)` with its `// RESET` block; atoms `activityA`, `modeA`, `contextA`, `lastNudgedA`, `barShownA`, `barDismissedA`, `pendingA`, `latchA`, `countdownA`, `lastLightArmedA`, `lastApiA`, `standDownA`; module variables `root`, `session`, `settings`, `git`, `edited`, `cwd`. `tests/world.tsx` exports `world(on, opts)` returning the `World` below.

- [ ] **Step 1: Write the test world** `tests/world.tsx` (in-memory engine beneath the plugin; every `$` call the shell makes has an answer here):
```tsx
import { mock } from 'claude-code/testing'
import type { On } from 'claude-code'

export type World = {
  clock: ReturnType<typeof mock.clock>
  files: Map<string, string>
  submits: { text: string; origin: string }[]
  commands: string[]
  notices: string[]   // ui.toast lines — one per notify()
  logs: string[]      // ui.log lines — kept apart so counts on `notices` stay exact
  registered: { tools: string[]; commands: string[] }
  draft: { value: string }
  sessionId: { value: string }
  contextPct: { value: number | undefined }
  rateLimits: { value: { kind: string; percentUsed: number; resetsAt?: string }[] }
  git: { branch: string; status: string }
  askAnswer: { value: string | null }  // answers $.ui.ask and AskUserQuestion; null = dismissed
  clearRefused: { value: boolean }     // makes $.command.run({ command: 'clear' }) reject
}

export function world(on: On, opts: { now?: number; store?: Record<string, unknown>; files?: Record<string, string> } = {}): World {
  const w: World = {
    clock: mock.clock(on, { now: opts.now ?? 1_000_000 }),
    files: new Map(Object.entries(opts.files ?? {})),
    submits: [], commands: [], notices: [], logs: [],
    registered: { tools: [], commands: [] },
    draft: { value: '' }, sessionId: { value: 's1' }, contextPct: { value: undefined },
    rateLimits: { value: [] }, git: { branch: 'main\n', status: '' }, askAnswer: { value: null },
    clearRefused: { value: false },
  }
  mock.store(on, opts.store ?? {})
  mock.env(on, { CLAUDE_CONFIG_DIR: '/cfg', HOME: '/home/u' })
  on('fs.read', (_$, e) => {
    const t = w.files.get(e.path)
    return t === undefined ? { deny: `ENOENT ${e.path}` } : { value: t as never }
  })
  on('fs.write', (_$, e) => { w.files.set(e.path, e.text); return { value: undefined } })
  on('fs.exists', (_$, e) => ({ value: w.files.has((e as { path: string }).path) }))
  on('process.run', (_$, e) => {
    const a = e.argv.join(' ')
    const out = a.includes('symbolic-ref') ? w.git.branch : w.git.status
    return { value: { exitCode: 0, stdout: out, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('session.id', () => ({ value: w.sessionId.value }))
  on('session.cwd', () => ({ value: '/repo' }))
  on('session.repo', () => ({ value: { root: '/repo', remote: null, internal: false, name: 'repo', id: 'r' } }))
  on('session.usage', () => ({ value: { startedAt: 0, context: { window: 1_000_000, percent: w.contextPct.value }, rateLimits: w.rateLimits.value } }))
  on('prompt.read', () => ({ value: { text: w.draft.value, cursor: w.draft.value.length } }))
  on('prompt.submit', (_$, e) => { w.submits.push({ text: e.text, origin: e.origin.kind }); return { text: e.text, origin: e.origin } })
  on('prompt.edit', (_$, e) => ({ text: e.text, cursor: e.cursor }))
  on('command.run', (_$, e) => {
    if (e.command === 'clear' && w.clearRefused.value) throw new Error('clear refused')
    w.commands.push(e.command)
    return {}
  })
  on('command.register', (_$, e) => { w.registered.commands.push(e.name); return { value: { command: e.name } } })
  on('tool.register', (_$, e) => { w.registered.tools.push(e.name); return { value: { tool: `mcp__context-vigil-mod__${e.name}` } } })
  on('ui.toast', (_$, e) => { w.notices.push(e.text); return { value: undefined } })
  on('ui.log', (_$, e) => { w.logs.push(e.text); return { value: undefined } })
  on('ui.status', () => ({ value: undefined }))
  on('ui.render', ($, e) => { const { Box } = $.ui.resolve(e); return <Box /> })
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('session.measure', (_$, e) => ({ changed: e.changed }))
  on('turn.start', (_$, e) => e as never)
  on('turn.complete', (_$, e) => ({ text: e.answer }))
  on('classic.SessionStart', () => ({}))
  on('classic.FileChanged', () => ({}))
  on('classic.StopFailure', () => ({}))
  on('classic.PostModelSwitch', () => ({}))
  // AskUserQuestion — and $.ui.ask, which is not an op event but runs as this tool call.
  // Result shape { questions, answers: { [question]: label } } per the claude-code-tools typings.
  // A test that passes `answers` on the input gets them echoed; otherwise every question
  // gets w.askAnswer; null means the person dismissed the dialog.
  on('tool.call', (_$, e) => {
    const input = e as unknown as { tool: string; questions?: { question: string }[]; answers?: Record<string, string> }
    if (input.tool === 'AskUserQuestion') {
      if (input.answers) return { result: { questions: input.questions, answers: input.answers } } as never
      if (w.askAnswer.value === null) return { deny: 'dismissed' }
      const answer = w.askAnswer.value
      return { result: { questions: input.questions, answers: Object.fromEntries((input.questions ?? []).map(q => [q.question, answer])) } } as never
    }
    return { result: 'ok' } as never
  })
  return w
}

export const START = { cwd: '/repo', surface: 'terminal' as const, isInteractive: true }
export const turn = (id = 't') => ({ answer: 'a', durationMs: 1, isAborted: false, turnId: id, reason: 'answer' as const })
export const human = (text: string, kind: 'composer' | 'bridge' = 'composer') => ({ text, wait: false, origin: { kind } as never })
```
Note for the implementer: `turn.start`'s bottom answer must match `TurnStartResult`; if `e as never` is refused, read `export type TurnStartResult` in the typings and return that shape. If `PROBES.md` §3/§6 observed a different AskUserQuestion / `$.ui.ask` shape, change this stub and `extractAnswers` (Task 9) together. A hook that throws in `command.run` makes the caller's `$.command.run` reject (that is how `clearRefused` works); if the harness reports it differently, return `{ deny: 'clear refused' }` instead.

- [ ] **Step 2: Write the failing shell test** `tests/shell-foundation.test.tsx`:
```tsx
import { expect, test } from 'claude-code/testing'
import { NAME } from '../core/name'
import { START, human, turn, world } from './world'

const MIN = 60_000

test('session start registers commands and the tool, resolves the config dir', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  expect(w.registered.commands.sort()).toEqual(['vhandoff', 'vho', 'vsetup'])
  expect(w.registered.tools).toEqual(['vigil_handover'])
})

test('arm and disarm are logged to a per-session day file when auto mode is on', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await $.session.start(START)
  await $.prompt.submit(human('go'))
  await w.clock.advance(31 * MIN)
  await $.turn.complete(turn())
  const day = [...w.files.keys()].find(k => k.startsWith('/cfg/context-vigil-mod/events/'))
  expect(day).toMatch(/\/events\/\d{4}-\d{2}-\d{2}\/s1\.jsonl$/)
  expect(w.files.get(day ?? '')).toContain('"kind":"arm"')
  await $.prompt.submit(human('back'))
  expect(w.files.get(day ?? '')).toContain('"kind":"disarm"')
})

test('auto mode off: the mode still moves to auto, but no arm line is logged', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('go'))
  await w.clock.advance(31 * MIN)
  await $.turn.complete(turn())
  expect((await $.state.get({ plugin: 'context-vigil-mod', key: 'mode' })).value).toBe('auto')
  const text = [...w.files.values()].join('')
  expect(text).not.toContain('"kind":"arm"')
})

test('a draft sitting in the terminal box counts as you being here', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await $.session.start(START)
  await $.prompt.submit(human('go'))
  await w.clock.advance(31 * MIN)
  w.draft.value = 'half a thought'
  await $.turn.complete(turn())
  expect((await $.state.get({ plugin: 'context-vigil-mod', key: 'mode' })).value).toBe('attended')
  w.draft.value = ''
  await w.clock.advance(31 * MIN)
  await $.turn.complete(turn('2'))
  expect((await $.state.get({ plugin: 'context-vigil-mod', key: 'mode' })).value).toBe('auto')
})

test('git refresh: tool calls schedule one coalesced refresh of two commands, off a timer', async ($, on) => {
  let runs = 0
  on('process.run', (_$, e) => { runs++; return { value: { exitCode: 0, stdout: e.argv.includes('status') ? '' : 'main', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } } })
  const w = world(on)
  await $.session.start(START)
  await w.clock.advance(1500)          // let the session-start refresh run first
  runs = 0
  await $.tool.call({ tool: 'Edit', tool_use_id: 'u1', file_path: '/repo/a.ts', old_string: 'a', new_string: 'b' } as never)
  await $.tool.call({ tool: 'Bash', tool_use_id: 'u2', command: 'ls' } as never)
  expect(runs).toBe(0)
  await w.clock.advance(1500)
  expect(runs).toBe(2)
  await $.tool.call({ tool: 'Read', tool_use_id: 'u3', file_path: '/repo/a.ts' } as never)
  await w.clock.advance(1500)
  expect(runs).toBe(2)
})

test('classic installed: stands down with one notice; the state literal is NAME', async ($, on) => {
  const w = world(on, { files: { '/cfg/settings.json': JSON.stringify({ hooks: { Stop: [{ hooks: [{ type: 'command', command: '"/s/context-vigil/scripts/context-vigil" hook stop' }] }] } }) } })
  await $.session.start(START)
  expect(w.notices.filter(n => n.includes('standing down')).length).toBe(1)
  expect((await $.state.get({ plugin: NAME, key: 'standDown' } as never)).value).toBe(true)
})

test('a fresh session start resets module caches: a stale git timer neither blocks nor doubles the refresh', async ($, on) => {
  let runs = 0
  on('process.run', (_$, e) => { runs++; return { value: { exitCode: 0, stdout: e.argv.includes('status') ? '' : 'main', stderr: '', isStdoutTruncated: false, isStderrTruncated: false } } })
  const w = world(on)
  await $.session.start(START)          // schedules a refresh at +1500
  w.sessionId.value = 's9'
  await $.session.start(START)          // bindSession cancels it and schedules its own
  await w.clock.advance(1500)
  expect(runs).toBe(2)
})

test('classic.SessionStart returns watch paths for .git', async ($, on) => {
  world(on)
  await $.session.start(START)
  const r = await $.classic.SessionStart({ source: 'startup' } as never)
  expect(r.watchPaths).toEqual(['/repo/.git/HEAD', '/repo/.git/index'])
})
```
(The counting `process.run` hook is registered before `world()`. If the harness lets the world's own `process.run` answer first, move the counting hook after `world()`; either way exactly one of them must answer.)

- [ ] **Step 3: Run to see it fail** — `claude plugin test plugins/context-vigil-mod` → FAIL (no commands registered).

- [ ] **Step 4: Implement** — replace `hooks/register.tsx` with:
```tsx
import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'
import type { EventKind, Git, Settings } from '../types'
import { COMMANDS, TOOL, classicSessionPath, configRoot, eventsPath } from '../core/name'
import { DEFAULTS, STORE_KEY, loadSettings } from '../core/settings'
import { EMPTY_ACTIVITY, classifyOrigin, mode, record, transition } from '../core/arming'
import type { Signal } from '../core/arming'
import { appendLine, dayKey, makeRecord } from '../core/eventlog'
import { COALESCE_MS, GIT_ARGV, parseGit, touchesGit, watchPaths } from '../core/git'
import { INPUT_SCHEMA, TOOL_DESCRIPTION } from '../core/handover'
import { classicHooksInstalled } from '../core/interlock'
import { V } from '../core/voice'

// The effectful shell: the ONLY file that touches `$`. Decisions live in ../core.

const activityA = atom({ plugin: 'context-vigil-mod', key: 'activity' } as const, EMPTY_ACTIVITY)
const modeA = atom({ plugin: 'context-vigil-mod', key: 'mode' } as const, 'idle')
const contextA = atom({ plugin: 'context-vigil-mod', key: 'contextPct' } as const, null)
const lastNudgedA = atom({ plugin: 'context-vigil-mod', key: 'lastNudged' } as const, null)
const barShownA = atom({ plugin: 'context-vigil-mod', key: 'barShown' } as const, false)
const barDismissedA = atom({ plugin: 'context-vigil-mod', key: 'barDismissed' } as const, false)
const pendingA = atom({ plugin: 'context-vigil-mod', key: 'pending' } as const, null)
const latchA = atom({ plugin: 'context-vigil-mod', key: 'latch' } as const, null)
const countdownA = atom({ plugin: 'context-vigil-mod', key: 'countdownEndsAt' } as const, null)
const lastLightArmedA = atom({ plugin: 'context-vigil-mod', key: 'lastLightArmed' } as const, false)
const lastApiA = atom({ plugin: 'context-vigil-mod', key: 'lastApiAt' } as const, null)
const standDownA = atom({ plugin: 'context-vigil-mod', key: 'standDown' } as const, false)

// Module caches: rebuilt at session.start / after a hot reload.
let root = '/nonexistent'
let session = 'unknown'
let cwd = ''
let settings: Settings = DEFAULTS
let git: Git = { branch: null, dirty: [] }
let gitTimer: { cancel: () => void } | null = null
const edited = new Set<string>()
let dayText: Record<string, string> = {}

async function nowMs($: EngineInterface): Promise<number> {
  return $.clock.now()
}

async function log($: EngineInterface, kind: EventKind, fields: Record<string, unknown> = {}) {
  const now = await nowMs($)
  const path = eventsPath(root, dayKey(now), session)
  if (dayText[path] === undefined) dayText[path] = await $.fs.read(path).then(t => String(t)).catch(() => '')
  dayText[path] = appendLine(dayText[path] ?? '', makeRecord(now, session, kind, fields))
  await $.fs.write(path, dayText[path] ?? '').catch(() => {})
}

// PROBES.md §1 decides the channel; both are sent until it says otherwise.
async function notify($: EngineInterface, text: string) {
  $.ui.toast(text)
  $.ui.log(text)
}

// Every plugin prompt goes through here: from a timer, never awaited by the hook the turn waits on.
function submitSoon($: EngineInterface, text: string, delayMs = 0) {
  $.clock.after(delayMs, () => { void $.prompt.submit({ text }) })
}

async function observe($: EngineInterface, signal: Signal) {
  const now = await nowMs($)
  const prev = await read($, modeA)
  let act = record(await read($, activityA), signal)
  // Spec §2: a non-empty draft in the terminal box is you being here.
  if (signal.kind === 'agent-step' && (await $.prompt.read()).text.trim()) act = record(act, { kind: 'edit', at: now })
  await update($, activityA, () => act)
  const next = mode(act, now, settings)
  if (next === prev) return
  await update($, modeA, () => next)
  const t = transition(prev, next)
  if (t && settings.auto) {
    await log($, t, { from: prev, to: next, idleMs: act.lastHumanAt === null ? null : now - act.lastHumanAt, origin: act.lastHumanOrigin })
  }
}

async function refreshGit($: EngineInterface) {
  gitTimer = null
  const run = (argv: readonly string[]) =>
    $.process.run(argv, { cwd }).then(r => ({ exitCode: r.exitCode, stdout: r.stdout })).catch(() => ({ exitCode: 1, stdout: '' }))
  const [b, s] = await Promise.all([run(GIT_ARGV.branch), run(GIT_ARGV.status)])
  git = parseGit(b, s)
}

function scheduleGit($: EngineInterface) {
  if (gitTimer) return
  gitTimer = $.clock.after(COALESCE_MS, () => { void refreshGit($) })
}

// Resets every module cache and timer (pre-flight F3): a hot reload or a reused module
// must start clean. Tasks 12–15 add their own module variables to the RESET block.
async function bindSession($: EngineInterface) {
  // RESET (Task 11)
  gitTimer?.cancel()
  gitTimer = null
  git = { branch: null, dirty: [] }
  edited.clear()
  dayText = {}
  // RESET (Tasks 12–15 add lines here)
  root = configRoot({ CLAUDE_CONFIG_DIR: await $.env.get('CLAUDE_CONFIG_DIR'), HOME: await $.env.get('HOME') })
  session = await $.session.id()
  cwd = await $.session.cwd()
  settings = loadSettings(await $.store.get(STORE_KEY))
}

async function checkInterlock($: EngineInterface) {
  const text = await $.fs.read(`${root}/settings.json`).then(t => String(t)).catch(() => null)
  const record = await $.fs.exists(classicSessionPath(root, session)).catch(() => false)
  const classic = classicHooksInstalled(text) || record
  const was = await read($, standDownA)
  await update($, standDownA, () => classic)
  if (classic && !was) {
    await notify($, V.classicActive)
    await log($, 'standdown', { settingsHooks: classicHooksInstalled(text), sessionRecord: record })
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const r = await next(e)
    await bindSession($)
    await $.command.register({ name: COMMANDS.handover, description: V.cmdHandover })
    await $.command.register({ name: COMMANDS.handoff, description: V.cmdHandover })
    await $.command.register({ name: COMMANDS.setup, description: V.cmdSetup })
    await $.tool.register({ name: TOOL, description: TOOL_DESCRIPTION, inputSchema: INPUT_SCHEMA as unknown as Record<string, unknown> })
    await checkInterlock($)
    scheduleGit($)
    return r
  })

  on('classic.SessionStart', async ($, e, next) => {
    const r = await next(e)
    const repo = await $.session.repo().catch(() => null)
    if (!repo) return r
    return { ...r, watchPaths: [...(r.watchPaths ?? []), ...watchPaths(repo.root)] }
  })

  on('classic.FileChanged', async ($, e, next) => {
    scheduleGit($)
    return next(e)
  })

  on('prompt.submit', async ($, e, next) => {
    await observe($, { kind: 'prompt', origin: e.origin.kind, at: await nowMs($) })
    return next(e)
  })

  on('command.run', async ($, e, next) => {
    if (classifyOrigin(e.origin.kind) === 'human') await observe($, { kind: 'human-command', at: await nowMs($) })
    return next(e)
  })

  on('prompt.edit', async ($, e, next) => {
    await observe($, { kind: 'edit', at: await nowMs($) })
    return next(e)
  })

  on('turn.start', async ($, e, next) => {
    scheduleGit($)
    return next(e)
  })

  on('tool.call', async ($, e, next) => {
    const r = await next(e)
    const input = e as unknown as { tool: string; file_path?: unknown }
    await observe($, { kind: 'agent-step', at: await nowMs($) })
    if ((input.tool === 'Edit' || input.tool === 'Write') && typeof input.file_path === 'string') edited.add(input.file_path)
    if (touchesGit(input.tool)) scheduleGit($)
    return r
  })

  on('turn.complete', async ($, e, next) => {
    const now = await nowMs($)
    await observe($, { kind: 'agent-step', at: now })
    await update($, lastApiA, () => now)
    return next(e)
  })
}
```
If `claude plugin validate` refuses an atom key not used yet, it is fine to leave unused atoms out until the task that uses them; keep the names exactly as listed.

- [ ] **Step 5: Run the gates** — validate, test, typecheck: all clean (all earlier core tests still pass).

- [ ] **Step 6: Commit**
```bash
git add plugins/context-vigil-mod/hooks/register.tsx plugins/context-vigil-mod/tests/world.tsx plugins/context-vigil-mod/tests/shell-foundation.test.tsx
git commit -m "feat(context-vigil-mod): shell foundation — event log, notices, arming, git, interlock" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Fj6V4wmyLYFK41Ed3YAqf"
```

---

### Task 11a: Next-session name in the handover (owner request, 2026-10-04)

Spec §3 steps 1 and 4: the handover names the session that resumes it.

**Files:**
- Modify: `plugins/context-vigil-mod/types/index.d.ts` (`Fields` gains `session_name: string`; `Pending` gains `name: string`)
- Modify: `plugins/context-vigil-mod/core/handover.ts`, `core/voice.ts`
- Test: `tests/handover.test.ts`, `tests/voice.test.ts` (extend)

**Interfaces:**
- Produces: `FIELD_NAMES` ends with `'session_name'`; `session_name` is REQUIRED; `cleanName(raw: string): string`; `renderHandover` prints `**Next session:** <name>` on the line after the title; `V.renameFailed`.

- [ ] **Step 1: Write the failing tests** (extend `tests/handover.test.ts`):
  - `FIELD_NAMES` is `['goal', 'state', 'decisions', 'next_step', 'open_questions', 'failed_attempts', 'session_name']` and `INPUT_SCHEMA.required` is `['goal', 'state', 'next_step', 'session_name']`; `INPUT_SCHEMA.properties.session_name.description` mentions "name".
  - `parseFields` with `session_name` missing or blank → `{ ok: false }`, error naming `session_name`.
  - `cleanName('  vigil-mod:\n shell   flow ')` → `'vigil-mod: shell flow'` (whitespace and newlines collapse to single spaces, trimmed); a leading `/` is stripped (`'/clear x'` → `'clear x'`); longer than 60 code units → cut to 60 then trimmed; `parseFields` stores `cleanName`'d `session_name`, and a name that cleans to `''` is blank → error.
  - `renderHandover` output's second line is `**Next session:** <name>`, and `session_name` does NOT also appear as a `##` section.
  - Update every existing `good` / `fields` fixture to carry `session_name`.
  - `tests/voice.test.ts`: `V.renameFailed` is emoji-led.
- [ ] **Step 2: Run, see RED.**
- [ ] **Step 3: Implement.** `DESCRIBE.session_name = 'A short name for the session that resumes this work: 2–6 words saying what it will do next (e.g. "vigil-mod: shell handover flow"). It becomes the new session\'s name after the clear.'`; `REQUIRED` gains `'session_name'`; `parseFields` applies `cleanName` to `session_name` before the blank check; `renderHandover` skips `session_name` in the section loop and pushes `` `**Next session:** ${f.session_name}` ``, `''` after the title. `instructionText` lists "session name" among the fields. `V.renameFailed = '🏷️ couldn\'t name the new session — carrying on'`.
- [ ] **Step 4: Run all gates, GREEN.**
- [ ] **Step 5: Commit** `feat(context-vigil-mod): handover names the resuming session` (with the two trailer lines).

---

### Task 12: Shell — the handover flow and the vigil bar

**Task 11a amendments (bind this task):** the `tool.call` handler saves `name: parsed.fields.session_name` in the `Pending` it builds; every `Pending` literal in tests carries `name`. In the `classic.SessionStart` `source: 'clear'` branch, when a pending handover is consumed, start the rename from a timer BEFORE the resume submit: `$.clock.after(0, () => { void renameSession($, pending.name) })`, where top-level `async function renameSession($, name)` runs `$.command.run({ command: 'rename', args: name })`, logs `'rename'` `{ name }`, and on rejection notifies `V.renameFailed` and logs `'guard.wait'` `{ reason: 'rename-rejected' }` — never blocking the resume. `tests/world.tsx` records `command.run` calls (already in `w.commands`); add tests: a consumed pending handover produces a `rename` command with the handover's name before the resume submit; a rename rejection still resumes. (`EventKind` gains `'rename'` if it is a closed union.)
**Probe §7 amendment (bind this task):** a mod never sees its own `$.prompt.submit` in `prompt.submit`. Mark `awaiting.started = true` when the instruction prompt is submitted (in the submit timer once `$.prompt.submit` resolves), not in the `prompt.submit` hook; drop the `e.origin.kind === 'plugin' && e.text.includes(TOOL_FULL)` branch. Tests must not rely on the world echoing the mod's own submits through its `prompt.submit` hook.

**Files:**
- Modify: `plugins/context-vigil-mod/hooks/register.tsx`
- Test: `tests/shell-handover.test.tsx`, `tests/shell-bar.test.tsx`

**Interfaces:**
- Consumes: Task 1 (`pendingKey`, `Pending`, `Awaiting`), Task 5 (`nextThreshold`, `parseFields`, `renderHandover`, `instructionText`, `resumeText`, `injectText`), Task 6 (`clearGate`), Task 4 (`armed`, `onPhone`), Task 8 (`formatHHMM`), Task 11 helpers/atoms (`submitSoon`, `bindSession` RESET block).
- Produces (top-level functions later tasks call): `startHandover($, reason: PendingReason, resume: boolean)` (defers while latched), `scheduleClear($, unattended: boolean)`, `savePending($, p: Pending | null)`, `cancelCountdown($)`; atoms `awaitingA`, `deferredA`, `handoverCountA`; module variables `clearParked: boolean`, `unattendedClear: boolean`.

- [ ] **Step 1: Write the failing tests** `tests/shell-handover.test.tsx`:
```tsx
import { expect, test } from 'claude-code/testing'
import { START, human, turn, world } from './world'

const MIN = 60_000
const TOOL = 'mcp__context-vigil-mod__vigil_handover'
const call = (extra: Record<string, unknown> = {}) => ({ tool: TOOL, tool_use_id: 'h1', goal: 'G', state: 'S', next_step: 'N', ...extra })
const measure = (percent: number) => ({ context: { window: 1_000_000, percent }, rateLimits: [], changed: ['context'] as never })
const vho = { command: 'vho', args: '', origin: { kind: 'composer' } as never } as never

test('a requested handover: instruction → tool → file → clear → inject → resume', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.command.run(vho)
  await w.clock.settle()
  expect(w.submits.at(-1)?.text).toContain(TOOL)
  expect(w.submits.at(-1)?.origin).toBe('plugin')
  const r = await $.tool.call(call() as never)
  expect(String((r as { result?: unknown }).result)).toContain('/cfg/context-vigil-mod/handovers/s1-1.md')
  expect(w.files.get('/cfg/context-vigil-mod/handovers/s1-1.md')).toContain('## Goal')
  await w.clock.settle()
  expect(w.commands).toContain('clear')
  w.sessionId.value = 's2'
  const ss = await $.classic.SessionStart({ source: 'clear' } as never)
  expect(ss.additionalContext?.join('\n')).toContain('## Goal')
  await w.clock.advance(500)
  expect(w.submits.at(-1)?.text).toContain('Resume from the handover')
})

test('/vhandoff does the same as /vho', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run({ command: 'vhandoff', args: '', origin: { kind: 'composer' } as never } as never)
  await w.clock.settle()
  expect(w.submits.at(-1)?.text).toContain(TOOL)
})

test('bad tool input is denied so the model can retry', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run(vho)
  await w.clock.settle()
  const r = await $.tool.call(call({ state: '' }) as never)
  expect((r as { deny?: string }).deny).toContain('state')
})

test('no tool call: one retry, then a visible failure and no clear', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run(vho)
  await w.clock.settle()
  await $.turn.complete(turn('a'))
  await w.clock.settle()
  expect(w.submits.filter(s => s.text.includes(TOOL)).length).toBe(2)
  await $.turn.complete(turn('b'))
  await w.clock.settle()
  expect(w.notices).toContain("📜 Couldn't write a handover — nothing was cleared")
  expect(w.commands).not.toContain('clear')
})

test('a turn that ends before the instruction prompt was sent is not a missed attempt', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await $.session.start(START)
  await $.prompt.submit(human('go'))
  await w.clock.advance(31 * MIN)
  await $.tool.call({ tool: 'Bash', tool_use_id: 'b', command: 'ls' } as never)
  await $.session.measure(measure(36))      // arms the handover; the submit is still on its timer
  await $.turn.complete(turn('running'))    // the turn that was already running ends
  await w.clock.settle()
  expect(w.submits.filter(s => s.text.includes(TOOL)).length).toBe(1)
})

test('a draft in the box waits, then clears once it is gone', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run(vho)
  await w.clock.settle()
  w.draft.value = 'half a sen'
  await $.tool.call(call() as never)
  await w.clock.settle()
  expect(w.commands).not.toContain('clear')
  expect(w.notices).toContain('✍️ Handover waiting — there is a draft in your prompt box')
  w.draft.value = ''
  await w.clock.advance(2000)
  expect(w.commands).toContain('clear')
})

test('a refused /clear says so and keeps the handover pending', async ($, on) => {
  const w = world(on)
  w.clearRefused.value = true
  await $.session.start(START)
  await $.command.run(vho)
  await w.clock.settle()
  await $.tool.call(call() as never)
  await w.clock.settle()
  expect(w.notices).toContain('🧹 /clear was refused — the handover is still pending; /clear to resume from it')
  expect((await $.state.get({ plugin: 'context-vigil-mod', key: 'pending' })).value).toMatchObject({ path: '/cfg/context-vigil-mod/handovers/s1-1.md' })
})

test('auto mode at the threshold hands over by itself', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await $.session.start(START)
  await $.prompt.submit(human('go'))
  await w.clock.advance(31 * MIN)
  await $.turn.complete(turn())
  await $.session.measure(measure(36))
  await w.clock.settle()
  expect(w.submits.at(-1)?.text).toContain(TOOL)
})

test('clear resets lastNudged so the next crossing nudges again', async ($, on) => {
  const w = world(on, { store: { settings: { bar: false } } })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(36))
  expect(w.notices.filter(n => n.includes('Context at')).length).toBe(1)
  await $.classic.SessionStart({ source: 'clear' } as never)
  await $.session.measure(measure(5))
  await $.session.measure(measure(36))
  expect(w.notices.filter(n => n.includes('Context at')).length).toBe(2)
})

test('a pending handover is keyed by its session: offered to its own session only', async ($, on) => {
  const mine = { session: 's1', path: '/cfg/context-vigil-mod/handovers/s1-1.md', reason: 'request', markdown: '# MINE', resume: true, followUp: null, createdAt: 1 }
  const theirs = { ...mine, session: 'other', path: '/cfg/context-vigil-mod/handovers/other-1.md', markdown: '# THEIRS' }
  const w = world(on, { store: { 'pending:s1': mine, 'pending:other': theirs } })
  await $.session.start(START)
  expect(w.notices.some(n => n.includes('s1-1.md'))).toBe(true)
  expect(w.notices.some(n => n.includes('other-1.md'))).toBe(false)
  const ss = await $.classic.SessionStart({ source: 'clear' } as never)
  expect(ss.additionalContext?.join('\n')).toContain('# MINE')
  expect(ss.additionalContext?.join('\n')).not.toContain('# THEIRS')
  expect(await $.store.get('pending:other')).toMatchObject({ markdown: '# THEIRS' })
  expect(await $.store.get('pending:s1')).toBeUndefined()
})
```
(If `$.store` is not callable from a test body, assert the same through a second `session.start` with `w.sessionId.value = 'other'` and check its offer notice.)

`tests/shell-bar.test.tsx`:
```tsx
import { expect, test } from 'claude-code/testing'
import { START, human, world } from './world'

const MIN = 60_000
const TOOL = 'mcp__context-vigil-mod__vigil_handover'
const BAND = (hasSurvey = false) => ({ plugin: 'context-vigil-mod', surface: 'terminal' as const, component: 'AbovePrompt' as const, props: { hasSurvey, isWorking: false } as never })
const measure = (percent: number) => ({ context: { window: 1_000_000, percent }, rateLimits: [], changed: ['context'] as never })

test('no bar before the threshold; from the crossing it shows live % and the configured threshold', async ($, on) => {
  world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  let ui = await $.ui.mount(BAND())
  expect(await ui.find({ key: 'handover' })).toBeUndefined()
  await ui.unmount()
  await $.session.measure(measure(41))
  ui = await $.ui.mount(BAND())
  expect(await ui.find({ type: 'Text', text: /context 41% · threshold 35%/ })).toBeDefined()
  expect(await ui.find({ key: 'handover' })).toBeDefined()
  await ui.unmount()
})

test('1 starts the handover and hides the bar', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(36))
  const ui = await $.ui.mount(BAND())
  await ui.press({ key: 'handover' })
  await w.clock.settle()
  expect(w.submits.at(-1)?.text).toContain(TOOL)
  expect(await ui.find({ key: 'handover' })).toBeUndefined()
  await ui.unmount()
})

test('2 brings the bar back at the next step; 0 hides it silently until a clear', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(36))
  let ui = await $.ui.mount(BAND())
  await ui.press({ key: 'later' })
  expect(await ui.find({ key: 'handover' })).toBeUndefined()
  await ui.unmount()
  await $.session.measure(measure(41))
  ui = await $.ui.mount(BAND())
  expect(await ui.find({ key: 'handover' })).toBeDefined()
  await ui.press({ key: 'dismiss' })
  await ui.unmount()
  await $.session.measure(measure(46))
  ui = await $.ui.mount(BAND())
  expect(await ui.find({ key: 'handover' })).toBeUndefined()
  await ui.unmount()
  expect((await $.state.get({ plugin: 'context-vigil-mod', key: 'lastNudged' })).value).toBe(45)
  expect(w.notices.some(n => n.includes('Context at'))).toBe(false)
})

test('yields to survey, returns after', async ($, on) => {
  world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(36))
  let ui = await $.ui.mount(BAND(true))
  expect(await ui.find({ key: 'handover' })).toBeUndefined()
  await ui.unmount()
  ui = await $.ui.mount(BAND(false))
  expect(await ui.find({ key: 'handover' })).toBeDefined()
  await ui.unmount()
})

test('hotkeys are 1 / 2 / 0', async ($, on) => {
  world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(36))
  const ui = await $.ui.mount(BAND())
  const keys = await Promise.all(['handover', 'later', 'dismiss'].map(k => ui.find({ key: k })))
  expect(keys.map(k => (k as { props?: { hotkey?: string } } | undefined)?.props?.hotkey)).toEqual(['1', '2', '0'])
  await ui.unmount()
})

test('on the phone: a notice instead of the bar', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi', 'bridge'))
  await $.session.measure(measure(36))
  const ui = await $.ui.mount(BAND())
  expect(await ui.find({ key: 'handover' })).toBeUndefined()
  await ui.unmount()
  expect(w.notices).toContain('🕯️ Context at 36% — say "hand over" (or /vho) when you\'re ready 📜')
})

test('with the bar switched off: a notice instead of the bar, in the terminal too', async ($, on) => {
  const w = world(on, { store: { settings: { bar: false } } })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(36))
  const ui = await $.ui.mount(BAND())
  expect(await ui.find({ key: 'handover' })).toBeUndefined()
  await ui.unmount()
  expect(w.notices).toContain('🕯️ Context at 36% — say "hand over" (or /vho) when you\'re ready 📜')
})

// The Remote Control countdown: auto mode on, RC auto-clear allowed, last prompt from the phone.
async function countdownSession($: never, w: ReturnType<typeof world>) {
  const e = $ as unknown as { session: { start: (x: unknown) => Promise<unknown>; measure: (x: unknown) => Promise<unknown> }; prompt: { submit: (x: unknown) => Promise<unknown> }; tool: { call: (x: unknown) => Promise<unknown> } }
  await e.session.start(START)
  await e.prompt.submit(human('go', 'bridge'))
  await w.clock.advance(31 * MIN)
  await e.tool.call({ tool: 'Bash', tool_use_id: 'b', command: 'ls' })
  await e.session.measure(measure(36))
  await w.clock.settle()
  await e.tool.call({ tool: TOOL, tool_use_id: 'h', goal: 'G', state: 'S', next_step: 'N' })
  await w.clock.settle()
}

test('RC countdown: shown on the bar with Cancel on 0; runs out into the clear', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true, rcAutoClear: 'yes' } } })
  await countdownSession($ as never, w)
  expect(w.notices).toContain('🧹 Handing over in 30 s — send anything to cancel')
  const ui = await $.ui.mount(BAND())
  expect(await ui.find({ type: 'Text', text: /Handing over in \d+ s/ })).toBeDefined()
  const cancel = await ui.find({ key: 'cancel' })
  expect((cancel as { props?: { hotkey?: string } } | undefined)?.props?.hotkey).toBe('0')
  await ui.unmount()
  expect(w.commands).not.toContain('clear')
  await w.clock.advance(30_000)
  expect(w.commands).toContain('clear')
})

test('RC countdown: Cancel stops the clear and keeps the handover', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true, rcAutoClear: 'yes' } } })
  await countdownSession($ as never, w)
  const ui = await $.ui.mount(BAND())
  await ui.press({ key: 'cancel' })
  await ui.unmount()
  await w.clock.advance(60_000)
  expect(w.commands).not.toContain('clear')
  expect(w.notices).toContain('🧹 Handover countdown cancelled — the handover is saved; /clear to resume from it')
  expect((await $.state.get({ plugin: 'context-vigil-mod', key: 'pending' })).value).toMatchObject({ reason: 'threshold' })
})

test('RC countdown: sending anything cancels it', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true, rcAutoClear: 'yes' } } })
  await countdownSession($ as never, w)
  await $.prompt.submit(human('wait!', 'bridge'))
  await w.clock.advance(60_000)
  expect(w.commands).not.toContain('clear')
  expect(w.notices).toContain('🧹 Handover countdown cancelled — the handover is saved; /clear to resume from it')
})
```
(`FoundElement`'s shape is in `claude-code/testing` — if `props.hotkey` is not where the found element carries it, read `export type FoundElement` and adjust only that accessor. If typing `countdownSession`'s `$` as `Engine` from `claude-code/testing` works, use that instead of the cast.)

- [ ] **Step 2: Run to see them fail** — FAIL.

- [ ] **Step 3: Implement** — add to `register.tsx`. Imports to add at the top (merge names into the existing import line from the same module where one exists):
```tsx
import type { Awaiting, Pending, PendingReason } from '../types'
import { TOOL_FULL, handoverPath } from '../core/name'
import { pendingKey } from '../core/settings'
import { armed, onPhone } from '../core/arming'
import { injectText, instructionText, nextThreshold, parseFields, renderHandover, resumeText } from '../core/handover'
import { clearGate } from '../core/surfaces'
import type { WaitReason } from '../core/voice'
import { formatHHMM } from '../core/limits'
```
Atoms (beside the Task 11 atoms):
```tsx
const awaitingA = atom({ plugin: 'context-vigil-mod', key: 'awaiting' } as const, null as Awaiting | null)
const deferredA = atom({ plugin: 'context-vigil-mod', key: 'deferred' } as const, null as Awaiting | null)
const handoverCountA = atom({ plugin: 'context-vigil-mod', key: 'handoverCount' } as const, 0)
```
Module variables (beside the others):
```tsx
let clearParked = false
let unattendedClear = false
let lastWait: WaitReason | null = null
let retryTimer: { cancel: () => void } | null = null
```
Add to the `// RESET (Tasks 12–15 add lines here)` block in `bindSession`:
```tsx
  retryTimer?.cancel()
  retryTimer = null
  clearParked = false
  unattendedClear = false
  lastWait = null
```
Top-level functions:
```tsx
async function savePending($: EngineInterface, p: Pending | null) {
  const prev = await read($, pendingA)
  await update($, pendingA, () => p)
  if (p) await $.store.set(pendingKey(p.session), p)
  else await $.store.delete(pendingKey(prev?.session ?? session))
}

async function startHandover($: EngineInterface, reason: PendingReason, resume: boolean) {
  if (await read($, standDownA)) return
  if (await read($, latchA)) {
    // Spec §5: while latched the mod never submits; Task 14's checkLatch starts it later.
    await update($, deferredA, () => ({ reason, resume, attempts: 1, started: false }))
    await notify($, V.waiting('latched'))
    await log($, 'guard.wait', { reason: 'latched', deferred: reason })
    return
  }
  const pending = await read($, pendingA)
  if (pending && (reason === 'threshold' || reason === 'request')) { scheduleClear($, reason === 'threshold'); return }
  await update($, awaitingA, () => ({ reason, resume, attempts: 1, started: false }))
  await log($, 'handover.requested', { reason, resume })
  submitSoon($, instructionText(reason))
}

function scheduleClear($: EngineInterface, unattended: boolean) {
  unattendedClear = unattended
  clearParked = false
  retryTimer?.cancel()
  retryTimer = $.clock.after(0, () => { void tryClear($) })
}

async function tryClear($: EngineInterface) {
  retryTimer = null
  if (!(await read($, pendingA))) return
  await checkInterlock($)   // spec §7: at session start AND before every clear (TEMPORARY)
  const now = await nowMs($)
  const act = await read($, activityA)
  const gate = clearGate({
    now, draft: (await $.prompt.read()).text, onPhone: onPhone(act), lastBridgeAt: act.lastBridgeAt,
    rcAutoClear: settings.rcAutoClear, latched: (await read($, latchA)) !== null,
    countdownEndsAt: await read($, countdownA), classicActive: await read($, standDownA), unattended: unattendedClear,
  })
  if (gate.go) {
    lastWait = null
    await update($, countdownA, () => null)
    await log($, 'clear', { unattended: unattendedClear })
    try {
      await $.command.run({ command: 'clear' })
    } catch {
      clearParked = true
      await notify($, V.clearRejected)
      await log($, 'guard.wait', { reason: 'clear-rejected' })
    }
    return
  }
  if (gate.reason !== lastWait) {
    lastWait = gate.reason
    await notify($, V.waiting(gate.reason))
    await log($, 'guard.wait', { reason: gate.reason, recheckMs: gate.recheckMs })
  }
  if (gate.reason === 'countdown-start') await update($, countdownA, () => now + (gate.recheckMs ?? 0))
  if (gate.recheckMs === null) { clearParked = true; return }
  retryTimer = $.clock.after(gate.recheckMs, () => { void tryClear($) })
}

async function cancelCountdown($: EngineInterface) {
  if ((await read($, countdownA)) === null) return
  await update($, countdownA, () => null)
  retryTimer?.cancel()
  retryTimer = null
  clearParked = true
  lastWait = null
  await notify($, V.countdownCancelled)
  await log($, 'guard.wait', { reason: 'countdown-cancelled' })
}

async function showNudge($: EngineInterface, pct: number) {
  const act = await read($, activityA)
  if (settings.bar && !onPhone(act)) {
    if (await read($, barDismissedA)) return          // 0 hid it for this cycle: silent
    await update($, barShownA, () => true)
    await log($, 'bar', { action: 'shown', pct })
    return
  }
  await notify($, V.nudge(pct))
}
```
Hooks to add inside `register`:
```tsx
  on('session.measure', async ($, e, next) => {
    const pct = e.context.percent ?? null
    await update($, contextA, () => pct)
    if (pct !== null && !(await read($, standDownA))) {
      const due = nextThreshold(pct, settings, await read($, lastNudgedA))
      if (due !== null) {
        await update($, lastNudgedA, () => due)
        const now = await nowMs($)
        const act = await read($, activityA)
        await log($, 'threshold', { pct, step: due, mode: await read($, modeA) })
        if (armed(act, now, settings)) await startHandover($, 'threshold', true)
        else await showNudge($, pct)
      }
    }
    return next(e)
  })

  for (const command of [COMMANDS.handover, COMMANDS.handoff]) {
    on('command.run', { command }, async $ => {
      await startHandover($, 'request', true)
      return { text: V.handingOver }
    })
  }

  on('tool.call', { tool: TOOL_FULL } as never, async ($, e) => {
    const input = e as unknown as Record<string, unknown>
    const parsed = parseFields(input)
    if (!parsed.ok) return { deny: `${parsed.error} — call ${TOOL_FULL} again with every required field` }
    const awaiting = await read($, awaitingA)
    const reason = awaiting?.reason ?? 'request'
    const resume = awaiting?.resume ?? true
    await update($, awaitingA, () => null)
    const n = (await read($, handoverCountA)) + 1
    await update($, handoverCountA, () => n)
    const path = handoverPath(root, session, n)
    const now = await nowMs($)
    const markdown = renderHandover(parsed.fields, {
      session, at: new Date(now).toISOString(), cwd, branch: git.branch, dirty: git.dirty,
      edited: [...edited], contextPct: await read($, contextA),
    })
    await $.fs.write(path, markdown)
    await savePending($, { session, path, reason, markdown, resume, followUp: null, createdAt: now })
    await log($, 'handover.written', { reason, bytes: markdown.length, path })
    await notify($, reason === 'last_light' ? V.lastLightReady : V.handoverSaved(path))
    if (reason === 'threshold' || reason === 'request') scheduleClear($, reason === 'threshold')
    return { result: `Saved handover to ${path}` } as never
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)
    if (await read($, standDownA)) return next(e)
    const { Box, Button, Text } = $.ui.resolve(e)
    const countdown = await read($, countdownA)
    if (countdown !== null) {
      // The RC countdown is a safety control: drawn whenever it runs, bar setting or not.
      const left = Math.max(0, Math.ceil((countdown - (await nowMs($))) / 1000))
      return (
        <Box>
          <Text>{V.countdownLine(left)}   </Text>
          <Button key="cancel" hotkey="0" plain label={V.cancel} onPress={() => cancelCountdown($)} />
        </Box>
      )
    }
    if (!settings.bar || !(await read($, barShownA))) return next(e)
    const pct = (await read($, contextA)) ?? 0
    const step = (await read($, lastNudgedA)) ?? settings.nudgeAt
    const latch = await read($, latchA)
    return (
      <Box>
        <Text>{V.barLine(pct, settings.nudgeAt, latch ? formatHHMM(latch.resetsAtMs) : null)}   </Text>
        <Button key="handover" hotkey="1" plain label={V.barHandover} onPress={() => barChoice($, 'handover')} />
        <Text>   </Text>
        <Button key="later" hotkey="2" plain label={V.barLater(step + settings.step)} onPress={() => barChoice($, 'later')} />
        <Text>   </Text>
        <Button key="dismiss" hotkey="0" plain label={V.barDismiss} onPress={() => barChoice($, 'dismiss')} />
      </Box>
    )
  })
```
and the bar's one press handler (top-level):
```tsx
async function barChoice($: EngineInterface, action: 'handover' | 'later' | 'dismiss') {
  await update($, barShownA, () => false)
  if (action === 'dismiss') await update($, barDismissedA, () => true)
  await log($, 'bar', { action })
  if (action === 'handover') await startHandover($, 'request', true)
}
```
Extend the existing `classic.SessionStart` hook so a clear injects and resets (replace its body):
```tsx
  on('classic.SessionStart', async ($, e, next) => {
    const r = await next(e)
    const repo = await $.session.repo().catch(() => null)
    const watch = repo ? watchPaths(repo.root) : []
    if (e.source !== 'clear') return watch.length ? { ...r, watchPaths: [...(r.watchPaths ?? []), ...watch] } : r
    const pending = await read($, pendingA)
    if (pending) await savePending($, null)         // deletes pending:<old session>
    session = await $.session.id()
    edited.clear()
    await update($, lastNudgedA, () => null)
    await update($, barShownA, () => false)
    await update($, barDismissedA, () => false)
    await update($, countdownA, () => null)
    await update($, handoverCountA, () => 0)
    if (!pending) return r
    const follow = pending.followUp
    if (pending.resume || follow) submitSoon($, follow ?? resumeText(pending.path), 500)
    await log($, 'resume', { path: pending.path, reason: pending.reason, followUp: follow !== null })
    return { ...r, additionalContext: [...(r.additionalContext ?? []), injectText(pending.markdown)] }
  })
```
Extend `session.start` (after `checkInterlock`): restore this session's pending handover:
```tsx
    const stored = (await $.store.get(pendingKey(session))) as Pending | null | undefined
    if (stored && !(await read($, pendingA))) {
      await update($, pendingA, () => stored)
      await notify($, V.pendingOffer(stored.path))
    }
```
Extend `prompt.submit` (before `return next(e)`): mark our own instruction prompt as started, and let any other prompt cancel a running countdown:
```tsx
    const awaitingNow = await read($, awaitingA)
    if (awaitingNow && !awaitingNow.started && e.origin.kind === 'plugin' && e.text.includes(TOOL_FULL)) {
      await update($, awaitingA, () => ({ ...awaitingNow, started: true }))
    }
    if (e.origin.kind !== 'plugin') await cancelCountdown($)
```
Extend `turn.complete` (before `return next(e)`): the missed-call retry — only for the instruction prompt's own turn:
```tsx
    const awaitingNow = await read($, awaitingA)
    if (awaitingNow?.started) {
      if (awaitingNow.attempts < 2) {
        await update($, awaitingA, () => ({ ...awaitingNow, attempts: awaitingNow.attempts + 1, started: false }))
        submitSoon($, instructionText(awaitingNow.reason))
      } else {
        await update($, awaitingA, () => null)
        await notify($, V.handoverFailed)
        await log($, 'guard.wait', { reason: 'tool-not-called' })
      }
    }
```
(A turn that called the tool has already cleared `awaitingA` in the tool hook, so it is never counted.)

- [ ] **Step 4: Run the gates** — validate, test (all files), typecheck: clean.

- [ ] **Step 5: Commit**
```bash
git add plugins/context-vigil-mod/hooks/register.tsx plugins/context-vigil-mod/tests/shell-handover.test.tsx plugins/context-vigil-mod/tests/shell-bar.test.tsx
git commit -m "feat(context-vigil-mod): handover flow, clear gate, vigil bar and RC countdown" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Fj6V4wmyLYFK41Ed3YAqf"
```

---

### Task 13: Shell — last light

**Files:**
- Modify: `plugins/context-vigil-mod/hooks/register.tsx`
- Test: `tests/shell-last-light.test.tsx`
- Uses (no change expected): `tests/world.tsx` — its `AskUserQuestion` stub answers `$.ui.ask` from `w.askAnswer` (null = dismissed). If `PROBES.md` §6 observed a different `$.ui.ask` path, adjust the stub here.

**Interfaces:**
- Consumes: Task 7 (`fireAt`, `shouldFire`, `rearm`, `holdOnReturn`, `ttlFromLabel`, `TTL_1H`), Task 12 (`startHandover`, `scheduleClear`, `savePending`), Task 11 (`submitSoon`, `bindSession` RESET block).
- Produces: module variables `ttlMs`, `lastLightTimer`.

- [ ] **Step 1: Write the failing test** `tests/shell-last-light.test.tsx`:
```tsx
import { expect, test } from 'claude-code/testing'
import { START, human, turn, world } from './world'

const MIN = 60_000
const TOOL = 'mcp__context-vigil-mod__vigil_handover'
const measure = (percent: number) => ({ context: { window: 1_000_000, percent }, rateLimits: [], changed: ['context'] as never })
const write = { tool: TOOL, tool_use_id: 'h', goal: 'G', state: 'S', next_step: 'N' } as never
const LL = { store: { settings: { lastLight: true, nudgeAt: 90 } } }
const asks = (w: { submits: { text: string }[] }) => w.submits.filter(s => s.text.includes(TOOL)).length

test('fires at TTL − lead with both idle and context ≥ threshold; writes only, no clear', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())
  await w.clock.advance(54 * MIN)
  expect(asks(w)).toBe(0)
  await w.clock.advance(1 * MIN)
  expect(asks(w)).toBe(1)
  expect(w.submits.at(-1)?.text).toContain('Do not clear')
  await $.tool.call(write)
  await w.clock.settle()
  expect(w.notices).toContain('🌅 Last light: a handover is ready 📜 — carry on as normal, or /clear to resume from it ✨')
  expect(w.commands).not.toContain('clear')
})

test('loop guard: without a human prompt it never fires again; a human prompt re-arms it', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())
  await w.clock.advance(55 * MIN)
  await $.tool.call(write)
  await $.classic.SessionStart({ source: 'clear' } as never)   // pending consumed, still no human prompt
  await $.session.measure(measure(30))
  await $.turn.complete(turn('ll'))                              // its own turn refreshed the cache
  await w.clock.advance(60 * MIN)
  expect(asks(w)).toBe(1)                                        // disarmed — not blocked by pending
  await $.prompt.submit(human('back'))
  await $.turn.complete(turn('after'))
  await w.clock.advance(55 * MIN)
  expect(asks(w)).toBe(2)
})

test('below the threshold it does not fire; at the threshold it does', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(24))
  await $.turn.complete(turn())
  await w.clock.advance(56 * MIN)
  expect(asks(w)).toBe(0)
  await $.prompt.submit(human('more'))
  await $.session.measure(measure(25))
  await $.turn.complete(turn('2'))
  await w.clock.advance(56 * MIN)
  expect(asks(w)).toBe(1)
})

test('switched off it never fires', async ($, on) => {
  const w = world(on, { store: { settings: { lastLight: false, nudgeAt: 90 } } })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())
  await w.clock.advance(56 * MIN)
  expect(asks(w)).toBe(0)
  expect(w.submits.map(s => s.text)).toEqual(['hi'])
})

test('on return after expiry the prompt is held and the choice asked; resume carries it over', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())
  await w.clock.advance(55 * MIN)
  await $.tool.call(write)
  await $.turn.complete(turn('ll'))
  await w.clock.advance(70 * MIN)
  w.askAnswer.value = 'Resume from handover'
  const r = await $.prompt.submit(human('morning!'))
  expect((r as { drop?: string }).drop).toBeDefined()
  await w.clock.settle()
  expect(w.commands).toContain('clear')
  await $.classic.SessionStart({ source: 'clear' } as never)
  await w.clock.advance(500)
  expect(w.submits.at(-1)?.text).toBe('morning!')
  expect((await $.state.get({ plugin: 'context-vigil-mod', key: 'lastLightArmed' })).value).toBe(true)
})

test('carry on submits the held prompt unchanged into the same conversation', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())
  await w.clock.advance(55 * MIN)
  await $.tool.call(write)
  await $.turn.complete(turn('ll'))
  await w.clock.advance(70 * MIN)
  w.askAnswer.value = 'Carry on'
  await $.prompt.submit(human('morning!'))
  await w.clock.settle()
  expect(w.submits.at(-1)?.text).toBe('morning!')
  expect(w.commands).not.toContain('clear')
  expect((await $.state.get({ plugin: 'context-vigil-mod', key: 'pending' })).value).toBe(null)
})

test('a dismissed question carries on, so the held prompt is never lost', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())
  await w.clock.advance(55 * MIN)
  await $.tool.call(write)
  await $.turn.complete(turn('ll'))
  await w.clock.advance(70 * MIN)
  w.askAnswer.value = null
  await $.prompt.submit(human('morning!'))
  await w.clock.settle()
  expect(w.submits.at(-1)?.text).toBe('morning!')
})

test('a 1-hour cache fires; a switch to a 5-minute cache cancels the scheduled fire', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())                                  // schedules the 1 h fire
  await $.classic.PostModelSwitch({ cache_ttl: '5m' } as never)  // must cancel it
  await w.clock.advance(120 * MIN)
  expect(asks(w)).toBe(0)
  await $.classic.PostModelSwitch({ cache_ttl: '1h' } as never)  // that cache is long cold: no catch-up fire
  await w.clock.settle()
  expect(asks(w)).toBe(0)
  await $.prompt.submit(human('again'))
  await $.turn.complete(turn('2'))
  await w.clock.advance(55 * MIN)
  expect(asks(w)).toBe(1)
})
```
- [ ] **Step 2: Run to see it fail** — FAIL.

- [ ] **Step 3: Implement** — add imports:
```tsx
import { TTL_1H, fireAt, holdOnReturn, rearm, shouldFire, ttlFromLabel } from '../core/last-light'
```
Module variables:
```tsx
let ttlMs = TTL_1H
let lastLightTimer: { cancel: () => void } | null = null
```
Add to the `// RESET` block in `bindSession`:
```tsx
  lastLightTimer?.cancel()
  lastLightTimer = null
  ttlMs = TTL_1H
```
Top-level functions:
```tsx
function scheduleLastLight($: EngineInterface, lastApiAt: number, now: number) {
  lastLightTimer?.cancel()
  lastLightTimer = null
  if (!settings.lastLight) return
  const at = fireAt(lastApiAt, ttlMs)
  if (at === null || now >= lastApiAt + ttlMs) return   // no fire for a cache that is already cold
  lastLightTimer = $.clock.after(Math.max(0, at - now), () => { void maybeFireLastLight($) })
}

async function maybeFireLastLight($: EngineInterface) {
  lastLightTimer = null
  const now = await nowMs($)
  await observe($, { kind: 'agent-step', at: (await read($, activityA)).lastAgentAt ?? 0 })  // picks up a draft (spec §2)
  const verdict = shouldFire({
    enabled: settings.lastLight, mode: mode(await read($, activityA), now, settings),
    contextPct: await read($, contextA), threshold: settings.lastLightAt,
    pending: (await read($, pendingA)) !== null, latched: (await read($, latchA)) !== null,
    armed: await read($, lastLightArmedA),
  })
  if (!verdict.fire) return
  await update($, lastLightArmedA, () => false)
  await log($, 'last_light.fired', { contextPct: await read($, contextA) })
  await startHandover($, 'last_light', false)
}

async function askReturn($: EngineInterface, held: string) {
  const choice = await $.ui.ask(V.lastLightAsk, [V.lastLightResume, V.lastLightCarryOn]).catch(() => V.lastLightCarryOn)
  const resume = choice === V.lastLightResume
  await log($, 'last_light.choice', { choice: resume ? 'resume' : 'carry_on' })
  const pending = await read($, pendingA)
  if (resume && pending) {
    await savePending($, { ...pending, resume: false, followUp: held })
    scheduleClear($, false)
    return
  }
  await savePending($, null)
  await $.prompt.submit({ text: held, asUser: true })
}
```
(The `observe` call in `maybeFireLastLight` passes the existing `lastAgentAt` so it records no new agent activity — it only lets Task 11's draft check run.)

In the `prompt.submit` hook, BEFORE `observe(...)`, add the hold and the re-arm (the held branch re-arms too: it is a real human prompt):
```tsx
    const now = await nowMs($)
    if (rearm(await read($, lastLightArmedA), e.origin.kind)) await update($, lastLightArmedA, () => true)
    const pending = await read($, pendingA)
    const lastApi = await read($, lastApiA)
    if (holdOnReturn({ pendingIsLastLight: pending?.reason === 'last_light', origin: e.origin.kind, now, cacheExpiresAt: lastApi === null ? null : lastApi + ttlMs })) {
      await observe($, { kind: 'prompt', origin: e.origin.kind, at: now })
      const held = e.text
      $.clock.after(0, () => { void askReturn($, held) })
      return { drop: 'held by context-vigil-mod: last light asks first' }
    }
```
In the `turn.complete` hook, after `update($, lastApiA, …)`: `scheduleLastLight($, now, now)`.

The held text resubmitted after a clear is the person's own words: in Task 12's `classic.SessionStart` clear branch, replace `submitSoon($, follow ?? resumeText(pending.path), 500)` with
```tsx
    if (follow) $.clock.after(500, () => { void $.prompt.submit({ text: follow, asUser: true }) })
    else if (pending.resume) submitSoon($, resumeText(pending.path), 500)
```
Add a hook for the TTL — a switch also re-plans (or cancels) an already scheduled fire:
```tsx
  on('classic.PostModelSwitch', async ($, e, next) => {
    const ttl = (e as unknown as { cache_ttl?: string }).cache_ttl
    if (ttl) {
      ttlMs = ttlFromLabel(ttl)
      const lastApi = await read($, lastApiA)
      if (lastApi === null) { lastLightTimer?.cancel(); lastLightTimer = null }
      else scheduleLastLight($, lastApi, await nowMs($))
    }
    return next(e)
  })
```

- [ ] **Step 4: Run the gates** — clean.

- [ ] **Step 5: Commit**
```bash
git add plugins/context-vigil-mod/hooks/register.tsx plugins/context-vigil-mod/tests/shell-last-light.test.tsx
git commit -m "feat(context-vigil-mod): last light — write-only before the cache goes cold, ask on return" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Fj6V4wmyLYFK41Ed3YAqf"
```

---

### Task 14: Shell — limits latch and early stop

**Files:**
- Modify: `plugins/context-vigil-mod/hooks/register.tsx`
- Test: `tests/shell-limits.test.tsx`

**Interfaces:**
- Consumes: Task 8 (`latchFromStopFailure`, `latchFromMeasure`, `latchCleared`, `earlyStopDue`, `nextHop`, `RESUME_DELAY_MS`, `formatHHMM`), Task 5 (`limitResumeText`), Task 12 (`startHandover` — which already defers while latched — `deferredA`, `scheduleClear`, `savePending`, `clearParked`, `unattendedClear`).
- Produces: `setLatch($, l)`, `checkLatch($, limits)`, `scheduleResume($, at)`; atom `firedA` (`$.state` key `firedEarlyStops`, per session).

- [ ] **Step 1: Write the failing test** `tests/shell-limits.test.tsx`:
```tsx
import { expect, test } from 'claude-code/testing'
import { START, human, world } from './world'

const TOOL = 'mcp__context-vigil-mod__vigil_handover'
const HOUR = 3_600_000
const iso = (ms: number) => new Date(ms).toISOString()
const measure = (rateLimits: { kind: string; percentUsed: number; resetsAt?: string }[], percent = 10) =>
  ({ context: { window: 1_000_000, percent }, rateLimits, changed: ['rateLimits'] as never })
const asks = (w: { submits: { text: string }[] }) => w.submits.filter(s => s.text.includes(TOOL)).length
const write = { tool: TOOL, tool_use_id: 'h', goal: 'G', state: 'S', next_step: 'N' } as never

test('while latched nothing is submitted or cleared; at the lift the deferred handover runs', async ($, on) => {
  const w = world(on, { now: 1_000_000 })
  w.rateLimits.value = [{ kind: 'five_hour', percentUsed: 100, resetsAt: iso(1_000_000 + HOUR) }]
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.classic.StopFailure({ error: 'rate_limit' } as never)
  expect(w.notices.some(n => n.startsWith('⏳ Usage limit reached — resumes'))).toBe(true)
  await $.command.run({ command: 'vho', args: '', origin: { kind: 'composer' } as never } as never)
  await w.clock.settle()
  expect(asks(w)).toBe(0)
  expect(w.notices).toContain('⏳ Handover waiting — the usage limit is in force')
  await w.clock.advance(HOUR + 1000)
  await $.session.measure(measure([{ kind: 'five_hour', percentUsed: 1, resetsAt: iso(1_000_000 + 6 * HOUR) }]))
  await w.clock.settle()
  expect(w.notices).toContain('⏳ Usage limit lifted — back to normal')
  expect(asks(w)).toBe(1)
  await $.tool.call(write)
  await w.clock.settle()
  expect(w.commands).toContain('clear')
})

test('a clear parked by the latch goes ahead when it lifts', async ($, on) => {
  const w = world(on, { now: 1_000_000 })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.command.run({ command: 'vho', args: '', origin: { kind: 'composer' } as never } as never)
  await w.clock.settle()
  w.rateLimits.value = [{ kind: 'five_hour', percentUsed: 100, resetsAt: iso(1_000_000 + HOUR) }]
  await $.classic.StopFailure({ error: 'rate_limit' } as never)   // latched between instruction and write
  await $.tool.call(write)
  await w.clock.settle()
  expect(w.commands).not.toContain('clear')
  await w.clock.advance(HOUR + 2000)                             // the latch's own timer lifts it at resetsAt
  expect(w.commands).toContain('clear')
})

test('seven_day at the trigger: handover once per window, then one resume after the reset', async ($, on) => {
  const w = world(on, { now: 1_000_000 })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  const resetsAt = iso(1_000_000 + 3 * HOUR)
  await $.session.measure(measure([{ kind: 'seven_day', percentUsed: 96, resetsAt }]))
  await w.clock.settle()
  expect(asks(w)).toBe(1)
  await $.session.measure(measure([{ kind: 'seven_day', percentUsed: 97, resetsAt }]))
  await w.clock.settle()
  expect(asks(w)).toBe(1)
  await $.tool.call(write)
  await w.clock.settle()
  expect(w.commands).not.toContain('clear')
  await w.clock.advance(3 * HOUR + 300_000)
  expect(w.submits.at(-1)?.text).toContain('limit has reset')
  expect(w.submits.filter(s => s.text.includes('limit has reset')).length).toBe(1)
  expect((await $.state.get({ plugin: 'context-vigil-mod', key: 'pending' })).value).toBe(null)
})

test('configured trigger and windows: below or unwatched does nothing; the watched window at its trigger fires', async ($, on) => {
  const w = world(on, { store: { settings: { limitPct: 98, limitWindows: ['spend_limit'] } } })
  await $.session.start(START)
  await $.session.measure(measure([{ kind: 'seven_day', percentUsed: 99, resetsAt: iso(5 * HOUR) }, { kind: 'spend_limit', percentUsed: 97, resetsAt: iso(5 * HOUR) }]))
  await w.clock.settle()
  expect(asks(w)).toBe(0)
  await $.session.measure(measure([{ kind: 'spend_limit', percentUsed: 98, resetsAt: iso(5 * HOUR) }]))
  await w.clock.settle()
  expect(asks(w)).toBe(1)
})
```

- [ ] **Step 2: Run to see it fail** — FAIL.

- [ ] **Step 3: Implement** — add imports (merge into existing lines where the module is already imported):
```tsx
import { RESUME_DELAY_MS, earlyStopDue, latchCleared, latchFromMeasure, latchFromStopFailure, nextHop } from '../core/limits'
import { limitResumeText } from '../core/handover'
import type { Latch, RateLimit } from '../types'
```
Atom (beside the others):
```tsx
const firedA = atom({ plugin: 'context-vigil-mod', key: 'firedEarlyStops' } as const, [] as string[])
```
Top-level functions:
```tsx
async function setLatch($: EngineInterface, l: Latch) {
  if (!l || (await read($, latchA))) return
  await update($, latchA, () => l)
  await log($, 'limit.latched', { kind: l.kind, resetsAtMs: l.resetsAtMs })
  await notify($, V.limitLatched(formatHHMM(l.resetsAtMs)))
  const now = await nowMs($)
  $.clock.after(Math.max(0, l.resetsAtMs - now) + 1000, () => { void checkLatch($, []) })
}

async function checkLatch($: EngineInterface, limits: RateLimit[]) {
  const l = await read($, latchA)
  if (!latchCleared(l, await nowMs($), limits)) return
  await update($, latchA, () => null)
  await log($, 'limit.cleared', { kind: l?.kind })
  await notify($, V.limitCleared)
  const deferred = await read($, deferredA)
  if (deferred) {
    await update($, deferredA, () => null)
    await startHandover($, deferred.reason, deferred.resume)
    return
  }
  if (clearParked && (await read($, pendingA))) scheduleClear($, unattendedClear)
}

// Waits in ≤ 1 h hops; never submits while latched (spec §5); clears the
// limit handover once the resume is sent so a later /clear does not re-inject it.
function scheduleResume($: EngineInterface, at: number) {
  $.clock.after(0, async () => {
    const wait = nextHop(await nowMs($), at)
    if (wait > 0) { $.clock.after(wait, () => { scheduleResume($, at) }); return }
    if (await read($, latchA)) { $.clock.after(60_000, () => { scheduleResume($, at) }); return }
    const pending = await read($, pendingA)
    await $.prompt.submit({ text: limitResumeText(pending?.path ?? '(no file)') })
    if (pending?.reason === 'limit') await savePending($, null)
  })
}
```
Hooks:
```tsx
  on('classic.StopFailure', async ($, e, next) => {
    const error = String((e as unknown as { error?: unknown }).error ?? '')
    const usage = await $.session.usage().catch(() => null)
    await setLatch($, latchFromStopFailure(error, usage?.rateLimits ?? [], await nowMs($)))
    return next(e)
  })
```
In the `session.measure` hook, before the threshold logic:
```tsx
    const limits = e.rateLimits as RateLimit[]
    await setLatch($, latchFromMeasure(limits))
    await checkLatch($, limits)
    const fired = await read($, firedA)
    const due = earlyStopDue(limits, settings, fired)
    if (due && !(await read($, standDownA))) {
      await update($, firedA, () => [...fired, due.key].slice(-20))
      await log($, 'limit.early_stop', { kind: due.kind, pct: due.pct, resetsAtMs: due.resetsAtMs })
      await notify($, V.earlyStop(due.kind, due.pct, formatHHMM(due.resetsAtMs + RESUME_DELAY_MS)))
      await startHandover($, 'limit', false)
      scheduleResume($, due.resetsAtMs + RESUME_DELAY_MS)
    }
```
(`scheduleResume` is a plain top-level function holding `$`, which is what the validator requires. `firedA` lives in `$.state`, so each session keeps its own marks; a restarted process may re-fire once — accepted in the ledger.)

- [ ] **Step 4: Run the gates** — clean.

- [ ] **Step 5: Commit**
```bash
git add plugins/context-vigil-mod/hooks/register.tsx plugins/context-vigil-mod/tests/shell-limits.test.tsx
git commit -m "feat(context-vigil-mod): limit latch and configurable 7-day/spend early stop" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Fj6V4wmyLYFK41Ed3YAqf"
```

---

### Task 15: Shell — setup cards and the first-RC question

**Files:**
- Modify: `plugins/context-vigil-mod/hooks/register.tsx`
- Test: `tests/shell-setup.test.tsx`

**Interfaces:**
- Consumes: Task 9 (`questionFor`, `nextCard`, `isStep`, `stepForQuestion`, `applyAnswers`, `extractAnswers`), Task 6 (`needsRcQuestion`), Task 4 (`onPhone`), Task 11 (`observe`, `submitSoon`, `bindSession` RESET block), Task 12 (`scheduleClear`, `clearParked`), `PROBES.md` §3 (answers location) and §5 (result `context` reaches the model).
- Produces: `startSetup($, only?: string)`, `cardPrompt(questions)`; atom `rcAskedA`.

- [ ] **Step 1: Write the failing test** `tests/shell-setup.test.tsx`:
```tsx
import { expect, test } from 'claude-code/testing'
import { START, human, world } from './world'

const MIN = 60_000
const TOOL = 'mcp__context-vigil-mod__vigil_handover'
const ask = (questions: { question: string }[], answers: Record<string, string>) =>
  ({ tool: 'AskUserQuestion', tool_use_id: 'q', questions, answers })
const cardOf = (text: string) => JSON.parse(text.slice(text.indexOf('[{'), text.lastIndexOf('}]') + 2)) as { header: string; question: string }[]
const setup = (args = '') => ({ command: 'vsetup', args, origin: { kind: 'composer' } as never } as never)

test('/vsetup asks card 1 through the model, saves the answers, follows with card 2', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run(setup())
  await w.clock.settle()
  const prompt = w.submits.at(-1)?.text ?? ''
  expect(prompt).toContain('AskUserQuestion')
  const card = cardOf(prompt)
  expect(card.map(q => q.header)).toEqual(['🎚️ Nudge at', '🎛️Vigil bar', '🤖 Auto mode', '🌅Last light'])
  const answers = Object.fromEntries(card.map(q => [q.question, q.header.includes('Auto') ? 'On' : q.header.includes('Nudge') ? '50%' : 'Off']))
  const r = await $.tool.call(ask(card, answers) as never)
  const next = JSON.stringify((r as { context?: string[] }).context ?? [])
  expect(next).toContain('⏱️Idle time')
  expect(next).toContain('⏳ Limits')
  expect(next).not.toContain('⏳ Trigger %')
  expect(await $.store.get('settings')).toMatchObject({ nudgeAt: 50, bar: false, auto: true, lastLight: false })
})

test('Tell me more re-asks that question with the explanation', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run(setup('bar'))
  await w.clock.settle()
  const card = cardOf(w.submits.at(-1)?.text ?? '')
  const r = await $.tool.call(ask(card, { [card[0]?.question ?? '']: 'Tell me more' }) as never)
  expect(JSON.stringify((r as { context?: string[] }).context ?? [])).toContain('A one-line bar')
})

test('answers to questions that are not ours are left alone', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run(setup('bar'))
  await w.clock.settle()
  const r = await $.tool.call(ask([{ question: 'Unrelated?' }], { 'Unrelated?': 'A' }) as never)
  expect((r as { context?: string[] }).context).toBeUndefined()
  expect(w.notices).not.toContain('⚙️ context-vigil-mod settings saved')
  expect(await $.store.get('settings')).toBeUndefined()
})

test('/vsetup with an unknown step shows the usage, asks nothing, saves nothing', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run(setup('bogus'))
  await w.clock.settle()
  expect(w.notices).toContain('⚙️ /vsetup [nudge|bar|auto|last-light|limits|rc] — that step name is not one of these')
  expect(w.notices).not.toContain('⚙️ context-vigil-mod settings saved')
  expect(w.submits.some(s => s.text.includes('AskUserQuestion'))).toBe(false)
})

// Auto mode arming in a session whose last human prompt came from the phone.
async function armOnPhone($: never, w: ReturnType<typeof world>) {
  const e = $ as unknown as { session: { start: (x: unknown) => Promise<unknown> }; prompt: { submit: (x: unknown) => Promise<unknown> }; tool: { call: (x: unknown) => Promise<unknown> } }
  await e.session.start(START)
  await e.prompt.submit(human('go', 'bridge'))
  await w.clock.advance(31 * MIN)
  await e.tool.call({ tool: 'Bash', tool_use_id: 'b', command: 'ls' })   // auto mode would arm now
  await w.clock.settle()
}

test('the RC question is asked once, when auto mode would first arm on the phone', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await armOnPhone($ as never, w)
  expect(w.notices).toContain('📱 First Remote Control session with auto mode — one quick question about auto-clear')
  expect(w.submits.filter(s => s.text.includes('📱 RC clear')).length).toBe(1)
  await $.prompt.submit(human('back', 'bridge'))
  await w.clock.advance(31 * MIN)
  await $.tool.call({ tool: 'Bash', tool_use_id: 'b2', command: 'ls' } as never)
  await w.clock.settle()
  expect(w.submits.filter(s => s.text.includes('📱 RC clear')).length).toBe(1)
})

test('RC answered Yes: saved, and the unattended clear on the phone goes through the countdown', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await armOnPhone($ as never, w)
  const card = cardOf(w.submits.at(-1)?.text ?? '')
  await $.tool.call(ask(card, { [card[0]?.question ?? '']: 'Yes' }) as never)
  expect(await $.store.get('settings')).toMatchObject({ rcAutoClear: 'yes' })
  await $.session.measure({ context: { window: 1_000_000, percent: 36 }, rateLimits: [], changed: ['context'] as never })
  await w.clock.settle()
  await $.tool.call({ tool: TOOL, tool_use_id: 'h', goal: 'G', state: 'S', next_step: 'N' } as never)
  await w.clock.settle()
  expect(w.notices).toContain('🧹 Handing over in 30 s — send anything to cancel')
  await w.clock.advance(30_000)
  expect(w.commands).toContain('clear')
})

test('RC answered No: saved, and the unattended clear on the phone never runs', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await armOnPhone($ as never, w)
  const card = cardOf(w.submits.at(-1)?.text ?? '')
  await $.tool.call(ask(card, { [card[0]?.question ?? '']: 'No' }) as never)
  expect(await $.store.get('settings')).toMatchObject({ rcAutoClear: 'no' })
  await $.session.measure({ context: { window: 1_000_000, percent: 36 }, rateLimits: [], changed: ['context'] as never })
  await w.clock.settle()
  await $.tool.call({ tool: TOOL, tool_use_id: 'h', goal: 'G', state: 'S', next_step: 'N' } as never)
  await w.clock.advance(60_000)
  expect(w.notices).toContain('📱 Handover saved — auto-clear is off for Remote Control sessions')
  expect(w.commands).not.toContain('clear')
})
```
(If `PROBES.md` §3 found the answers somewhere other than input/result, change `extractAnswers` and the world stub together. If §5 found that a tool result's `context` does not reach the model, change the follow-up path to `submitSoon($, cardPrompt(...))` and these tests to read the next card from `w.submits` instead of `r.context`. If `$.store` is not callable from a test body, read the saved settings back through a fresh `session.start` and a `/vsetup` card instead.)

- [ ] **Step 2: Run to see it fail** — FAIL.

- [ ] **Step 3: Implement** — add imports (merge into existing lines where the module is already imported):
```tsx
import { applyAnswers, extractAnswers, isStep, nextCard, questionFor, stepForQuestion } from '../core/setup'
import { needsRcQuestion } from '../core/surfaces'
import type { StepId } from '../types'
```
Atom and module variable:
```tsx
const rcAskedA = atom({ plugin: 'context-vigil-mod', key: 'rcAsked' } as const, false)
let setupRun: { only: string | undefined; asked: StepId[] } | null = null
```
Add to the `// RESET` block in `bindSession`:
```tsx
  setupRun = null
```
Top-level functions:
```tsx
function cardPrompt(questions: unknown[]): string {
  return 'context-vigil-mod setup: call the AskUserQuestion tool now with exactly these questions (JSON, use as-is): ' +
    `${JSON.stringify(questions)} — then stop; do nothing else this turn.`
}

async function startSetup($: EngineInterface, only?: string) {
  if (only !== undefined && !isStep(only)) { await notify($, V.setupUsage); return }
  setupRun = { only, asked: [] }
  const ids = nextCard(settings, [], only)
  if (!ids.length) { setupRun = null; await notify($, V.setupSaved); return }
  setupRun.asked.push(...ids)
  submitSoon($, cardPrompt(ids.map(id => questionFor(id))))
}

// Spec §2 / pre-flight F24: asked when auto mode would first arm on the phone.
async function maybeAskRc($: EngineInterface) {
  const act = await read($, activityA)
  if (!needsRcQuestion(onPhone(act), settings.rcAutoClear, settings.auto)) return
  if (setupRun || (await read($, rcAskedA))) return
  await update($, rcAskedA, () => true)
  await notify($, V.rcAsk)
  await log($, 'rc.answer', { asked: true })
  await startSetup($, 'rc')
}
```
In Task 11's `observe`, right after the `if (t && settings.auto) { await log(...) }` block, add:
```tsx
  if (t === 'arm') await maybeAskRc($)
```
Hooks:
```tsx
  on('command.run', { command: COMMANDS.setup }, async ($, e) => {
    await startSetup($, e.args.trim() || undefined)
    return { text: V.settingUp }
  })

  on('tool.call', { tool: 'AskUserQuestion' } as never, async ($, e, next) => {
    const r = await next(e)
    if (!setupRun) return r
    const pairs = Object.entries(extractAnswers(e, r))
      .map(([q, answer]) => ({ step: stepForQuestion(q), answer }))
      .filter((p): p is { step: StepId; answer: string } => p.step !== undefined)
    if (!pairs.length) return r
    const applied = applyAnswers(settings, pairs)
    settings = applied.settings
    await $.store.set(STORE_KEY, settings)
    await log($, 'setup', { steps: pairs.map(p => p.step), retell: applied.retell })
    if (pairs.some(p => p.step === 'rc')) await log($, 'rc.answer', { answer: settings.rcAutoClear })
    if (applied.retell.length) {
      return { ...r, context: [...(r.context ?? []), cardPrompt(applied.retell.map(id => questionFor(id, true)))] }
    }
    const ids = nextCard(settings, setupRun.asked, setupRun.only)
    if (ids.length) {
      setupRun.asked.push(...ids)
      return { ...r, context: [...(r.context ?? []), cardPrompt(ids.map(id => questionFor(id)))] }
    }
    setupRun = null
    await notify($, V.setupSaved)
    if (settings.rcAutoClear === 'yes' && clearParked && (await read($, pendingA))) scheduleClear($, true)
    return r
  })
```
(The prompt deliberately does not start with `[context-vigil-mod]`, so the card's JSON is the first `[{` in it.)

- [ ] **Step 4: Run the gates** — clean.

- [ ] **Step 5: Commit**
```bash
git add plugins/context-vigil-mod/hooks/register.tsx plugins/context-vigil-mod/tests/shell-setup.test.tsx
git commit -m "feat(context-vigil-mod): setup cards with Tell me more, RC question at first arm" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Fj6V4wmyLYFK41Ed3YAqf"
```

---

### Task 16: User-level install script (parallel with wave 1/2 — separate files)

**Files:**
- Create: `plugins/context-vigil-mod/scripts/install.sh`
- Test: `tests/context_vigil_mod/test_install.py` (repo root `tests/`)

**Interfaces:**
- Produces: `scripts/install.sh install|uninstall|status` operating on `$CLAUDE_CONFIG_DIR/settings.json` (fallback `$HOME/.claude/settings.json`), editing only `env.CLAUDE_CODE_PLUGIN_DIRS` (colon-separated). Refuses `install` while classic hooks are present (spec §7).

- [ ] **Step 1: Write the failing test** `tests/context_vigil_mod/test_install.py`:
```python
"""install.sh edits only env.CLAUDE_CODE_PLUGIN_DIRS in the account's own settings.json.

Isolation: every run pins CLAUDE_CONFIG_DIR and HOME into tmp_path (repo CLAUDE.md).
"""
import json
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "plugins" / "context-vigil-mod" / "scripts" / "install.sh"
PLUGIN = str(SCRIPT.parent.parent)


def run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "CLAUDE_CONFIG_DIR": str(tmp_path / "cfg"), "HOME": str(tmp_path / "home")}
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True)


def settings(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "cfg" / "settings.json").read_text())


def test_install_creates_and_appends(tmp_path):
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "settings.json").write_text(json.dumps({"env": {"CLAUDE_CODE_PLUGIN_DIRS": "/other"}, "model": "opus"}))
    r = run(tmp_path, "install")
    assert r.returncode == 0, r.stderr
    s = settings(tmp_path)
    assert s["env"]["CLAUDE_CODE_PLUGIN_DIRS"] == f"/other:{PLUGIN}"
    assert s["model"] == "opus"


def test_install_is_idempotent(tmp_path):
    run(tmp_path, "install")
    run(tmp_path, "install")
    assert settings(tmp_path)["env"]["CLAUDE_CODE_PLUGIN_DIRS"] == PLUGIN


def test_uninstall_removes_only_ours(tmp_path):
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "settings.json").write_text(json.dumps({"env": {"CLAUDE_CODE_PLUGIN_DIRS": f"/a:{PLUGIN}:/b"}}))
    assert run(tmp_path, "uninstall").returncode == 0
    assert settings(tmp_path)["env"]["CLAUDE_CODE_PLUGIN_DIRS"] == "/a:/b"


# Same fixture string as CLASSIC_CMD in plugins/context-vigil-mod/tests/interlock.test.ts (Task 10).
CLASSIC_CMD = '"/s/context-vigil/scripts/context-vigil" hook stop'


def test_refuses_while_classic_hooks_are_installed(tmp_path):
    (tmp_path / "cfg").mkdir()
    classic = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": CLASSIC_CMD}]}]}}
    (tmp_path / "cfg" / "settings.json").write_text(json.dumps(classic))
    r = run(tmp_path, "install")
    assert r.returncode == 3
    assert "uninstall classic" in r.stderr
    assert "CLAUDE_CODE_PLUGIN_DIRS" not in (tmp_path / "cfg" / "settings.json").read_text()


def test_status(tmp_path):
    assert "not installed" in run(tmp_path, "status").stdout
    run(tmp_path, "install")
    out = run(tmp_path, "status").stdout
    assert "context-vigil-mod: installed" in out
    assert "not installed" not in out


def test_other_hooks_do_not_block_install(tmp_path):
    (tmp_path / "cfg").mkdir()
    other = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "python3 ~/.claude-personal/census/five-hour-guard.py"}]}]}}
    (tmp_path / "cfg" / "settings.json").write_text(json.dumps(other))
    assert run(tmp_path, "install").returncode == 0
    s = settings(tmp_path)
    assert s["env"]["CLAUDE_CODE_PLUGIN_DIRS"] == PLUGIN
    assert s["hooks"] == other["hooks"]
```

- [ ] **Step 2: Run to see it fail**

Run: `poetry run pytest tests/context_vigil_mod/test_install.py -q`
Expected: FAIL (script missing). If poetry is unusable here, use the worktree `.venv`: `.venv/bin/pytest tests/context_vigil_mod/test_install.py -q`.

- [ ] **Step 3: Implement** `plugins/context-vigil-mod/scripts/install.sh`:
```bash
#!/usr/bin/env bash
# User-level install for context-vigil-mod: lists this plugin folder in
# env.CLAUDE_CODE_PLUGIN_DIRS of the CURRENT account's settings.json only
# ($CLAUDE_CONFIG_DIR, else ~/.claude). Never a repo's .claude/settings.json.
set -euo pipefail
cmd="${1:-status}"
plugin="$(cd "$(dirname "$0")/.." && pwd)"
cfg="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
file="$cfg/settings.json"
mkdir -p "$cfg"
[ -f "$file" ] || echo '{}' > "$file"
command -v jq >/dev/null || { echo "install.sh needs jq" >&2; exit 2; }

current=$(jq -r '.env.CLAUDE_CODE_PLUGIN_DIRS // ""' "$file")
# grep without -q: under pipefail, -q exiting early can SIGPIPE the writer.
has_ours() { printf '%s' "$current" | tr ':' '\n' | grep -Fx "$plugin" >/dev/null; }

write() {
  local tmp
  tmp=$(mktemp "$cfg/.settings.XXXXXX")
  jq --arg v "$1" 'if $v == "" then (.env |= (. // {} | del(.CLAUDE_CODE_PLUGIN_DIRS))) else (.env |= ((. // {}) + {CLAUDE_CODE_PLUGIN_DIRS: $v})) end' "$file" > "$tmp"
  mv "$tmp" "$file"
}

case "$cmd" in
  install)
    # Keep in step with CLASSIC in core/interlock.ts (same match, TS form). TEMPORARY: removed when classic retires.
    if jq -r '[.hooks // {} | .[]? | .[]? | .hooks[]? | .command? // ""] | .[]' "$file" | grep -E '/scripts/context-vigil"[[:space:]]+hook[[:space:]]' >/dev/null; then
      echo "classic context-vigil hooks are installed in $file — uninstall classic first, then re-run (spec §7)" >&2
      exit 3
    fi
    if has_ours; then echo "context-vigil-mod already installed in $file"; exit 0; fi
    if [ -z "$current" ]; then write "$plugin"; else write "$current:$plugin"; fi
    echo "context-vigil-mod installed in $file — start a new session, then run /vsetup"
    ;;
  uninstall)
    next=$(printf '%s' "$current" | tr ':' '\n' | grep -Fxv "$plugin" | paste -sd: - || true)
    write "$next"
    echo "context-vigil-mod removed from $file"
    ;;
  status)
    if has_ours; then echo "context-vigil-mod: installed ($file)"; else echo "context-vigil-mod: not installed ($file)"; fi
    ;;
  *) echo "usage: install.sh install|uninstall|status" >&2; exit 2 ;;
esac
```
Then `chmod +x plugins/context-vigil-mod/scripts/install.sh`. Add `tests/context_vigil_mod/__init__.py` only if the repo's other test folders have one (check `ls tests/*/__init__.py`).

- [ ] **Step 4: Run** — `poetry run pytest tests/context_vigil_mod -q` → PASS.

- [ ] **Step 5: Commit**
```bash
git add plugins/context-vigil-mod/scripts/install.sh tests/context_vigil_mod
git commit -m "feat(context-vigil-mod): user-level install script that refuses while classic is installed" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Fj6V4wmyLYFK41Ed3YAqf"
```

---

### Task 17: Docs and owner-run live smokes

**Files:**
- Create: `plugins/context-vigil-mod/README.md`, `plugins/context-vigil-mod/SMOKES.md`
- Modify: `CLAUDE.md` (repo root) — Plugins list

**Interfaces:**
- Consumes: everything shipped.

- [ ] **Step 1: Write `README.md`** — sections, each a few lines, using the exact names: what it is (mod, no tmux/status line), side by side with classic (personal = mod, work = classic), **install** (`bash plugins/context-vigil-mod/scripts/install.sh install` in the account to switch; uninstall classic's hooks from that account FIRST — the script refuses otherwise; then start a new session and run `/vsetup`), commands (`/vho`, `/vhandoff`, `/vsetup [nudge|bar|auto|last-light|limits|rc]`), the three states table from spec §2, the vigil bar (1/2/0, threshold-only, yields to the survey, toggle via `/vsetup bar`), last light (writes only; asks on return), limits (latch; configurable early stop; 5-hour left to Claude Code), files (`$CLAUDE_CONFIG_DIR/context-vigil-mod/handovers/`, `events/<day>/<session>.jsonl`), and **Temporary interlock** (removed when classic retires).

- [ ] **Step 2: Write `SMOKES.md`** — an owner-run checklist (the auto-mode classifier forbids an agent driving another session), each item with expected result and a blank result line:
  1. Terminal: `/vho` → instruction turn → `vigil_handover` called → file under `handovers/` → `/clear` runs by itself → handover injected → resume prompt.
  2. Terminal: type a draft, then `/vho` → waits with the ✍️ notice; delete the draft → clears within 2 s.
  3. Bar: push context past 35% → bar shows `context NN% · threshold 35%`; `1` starts a handover; `2` hides until the next step; `0` hides it silently until a clear (no notice); feedback survey appearing hides the bar and it returns after.
  4. Phone (RC): auto mode on, idle window 15 min via `/vsetup auto`, work from the phone → when auto mode first arms, the `📱 RC clear` question is asked (once). With Yes: at the threshold the 30 s countdown notice reaches the phone, the terminal bar shows the countdown with `0: ✖ Cancel`; pressing 0 or sending a message cancels it. With No: the handover is saved and nothing clears.
  5. Last light: `/vsetup last-light` On; leave idle ~55 min at ≥ 25% → handover written, nothing cleared; come back after the hour → the resume/carry-on dialog, held message re-sent either way.
  6. Limits: force a `rate_limit` (or wait for one) → `⏳ resumes HH:MM` notice, no clear until lifted.
  7. Coexistence: with classic installed in the account → one "standing down" notice, nothing else happens.
  8. Event log: `events/<today>/<session>.jsonl` holds `threshold`, `handover.written`, `clear`, `resume` lines with reasons.

- [ ] **Step 3: Add the plugin to the repo `CLAUDE.md` Plugins list** (alphabetical, after `chronicle`):
```markdown
- **context-vigil-mod** — context handover as a Claude Code mod (no tmux, no status line): threshold nudge + vigil bar, auto handover with in-process /clear and resume, last light, limit latch and configurable early stop; runs side by side with classic context-vigil; no skills (commands /vho, /vhandoff, /vsetup)
```

- [ ] **Step 4: Run all gates once more** — validate, plugin test, typecheck, pytest install test: clean.

- [ ] **Step 5: Commit**
```bash
git add plugins/context-vigil-mod/README.md plugins/context-vigil-mod/SMOKES.md CLAUDE.md
git commit -m "docs(context-vigil-mod): README, owner smoke checklist, plugin list entry" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016Fj6V4wmyLYFK41Ed3YAqf"
```

---

### Task 18: Final whole-branch review

**Files:** none changed by the reviewer; fixes go through new implementer rounds.

- [ ] **Step 1: Dispatch one fresh reviewer on the most capable model** with: the spec, this plan, `git diff main...feat/context-vigil-mod`, `PROBES.md`. Ask specifically for: any `$` use outside `register.tsx`; any `$.command.run`/`$.prompt.submit` awaited inside a hook the turn waits on; any write outside `$CLAUDE_CONFIG_DIR/context-vigil-mod/`; the five Review Focus items; spec §2–§7 behaviours with no test; strings not from `voice.ts`; header lengths.
- [ ] **Step 2: Fix Critical and Important findings** via implementer rounds (each with a failing test first), re-run all gates.
- [ ] **Step 3: Owner runs `SMOKES.md`**; record results in it; commit.
- [ ] **Step 4: Hand back** for the owner's merge decision (superpowers:finishing-a-development-branch). Do not merge or push without the owner.

---

## Deferred (not in this plan)

- **Interlock removal (cleanup when classic retires):** delete `core/interlock.ts`, `classicSessionPath` in `core/name.ts`, `checkInterlock` and `standDownA` use in `register.tsx`, the classic refusal in `install.sh` (and its `CLASSIC_CMD` fixture test), the interlock tests, and the README section. Then retire classic. Trigger: side-by-side run done and the owner picks the mod.
- **Status-line band** (replacing `statusline-command.sh` with a mod band): parked by the owner. When it returns, re-add git `ahead` (dropped in pre-flight F30).
- **Last light's early band on `prompt.edit`** (spec §4 "may"): raising the resume/carry-on choice as a band while the person is still typing, before they send.
- **Removing the TEMP vigil-probe block** in `~/.claude/statusline-command.sh` and the throwaway dev mods (`vigil-probe`, `vigil-bar-demo`, `handover-spike`, `cvm-probe`): owner housekeeping, outside the repo.
