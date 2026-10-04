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
