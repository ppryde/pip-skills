import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'
import type { Awaiting, EventKind, Git, Latch, Mode, Pending, PendingReason, RateLimit, Settings } from '../types'
import { COMMANDS, TOOL, TOOL_FULL, classicSessionPath, configRoot, eventsPath, handoverPath } from '../core/name'
import { DEFAULTS, STORE_KEY, loadSettings, pendingKey } from '../core/settings'
import { EMPTY_ACTIVITY, armed, classifyOrigin, mode, onPhone, record, transition } from '../core/arming'
import type { Signal } from '../core/arming'
import { appendLine, dayKey, makeRecord } from '../core/eventlog'
import { COALESCE_MS, GIT_ARGV, parseGit, touchesGit, watchPaths } from '../core/git'
import { INPUT_SCHEMA, TOOL_DESCRIPTION, injectText, instructionText, limitResumeText, nextThreshold, parseFields, renderHandover, resumeText } from '../core/handover'
import { TTL_1H, fireAt, holdOnReturn, rearm, shouldFire, ttlFromLabel } from '../core/last-light'
import { clearGate } from '../core/surfaces'
import { RESUME_DELAY_MS, earlyStopDue, formatHHMM, latchCleared, latchFromMeasure, latchFromStopFailure, nextHop } from '../core/limits'
import { classicHooksInstalled } from '../core/interlock'
import { V } from '../core/voice'
import type { WaitReason } from '../core/voice'

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
const awaitingA = atom({ plugin: 'context-vigil-mod', key: 'awaiting' } as const, null as Awaiting | null)
const deferredA = atom({ plugin: 'context-vigil-mod', key: 'deferred' } as const, null as Awaiting | null)
const firedA = atom({ plugin: 'context-vigil-mod', key: 'firedEarlyStops' } as const, [] as string[])
const handoverCountA = atom({ plugin: 'context-vigil-mod', key: 'handoverCount' } as const, 0)

// Module caches: rebuilt at session.start / after a hot reload.
let root = '/nonexistent'
let session = 'unknown'
let cwd = ''
let settings: Settings = DEFAULTS
let git: Git = { branch: null, dirty: [] }
let gitTimer: { cancel: () => void } | null = null
const edited = new Set<string>()
let dayText: Record<string, string> = {}
let clearParked = false
let unattendedClear = false
let lastWait: WaitReason | null = null
let retryTimer: { cancel: () => void } | null = null
let ttlMs = TTL_1H
let lastLightTimer: { cancel: () => void } | null = null

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
  await Promise.all([$.ui.toast(text), $.ui.log(text)]).catch(() => {})
}

// Every plugin prompt goes through here: from a timer, never awaited by the hook the turn waits on.
function submitSoon($: EngineInterface, text: string, delayMs = 0, onSent?: () => void, onFailed?: () => void) {
  $.clock.after(delayMs, () => { void $.prompt.submit({ text }).then(() => onSent?.(), () => onFailed?.()) })
}

// PROBES.md §7: a mod never sees its own submit in prompt.submit, so `started` is marked here.
function submitInstruction($: EngineInterface, reason: PendingReason) {
  submitSoon($, instructionText(reason), 0, () => {
    void update($, awaitingA, a => (a ? { ...a, started: true } : a))
  }, () => {
    // A rejected submit must not leave the handover waiting for a turn that never comes.
    void (async () => {
      await update($, awaitingA, () => null)
      await notify($, V.handoverFailed)
      await log($, 'guard.wait', { reason: 'submit-rejected' })
    })()
  })
}

async function observe($: EngineInterface, signal: Signal) {
  const now = await nowMs($)
  // Every change is computed from the value it replaces, so overlapping observers cannot erase each other.
  let act = await update($, activityA, a => record(a, signal))
  // Spec §2: a non-empty draft in the terminal box is you being here.
  if (signal.kind === 'agent-step' && (await $.prompt.read()).text.trim()) act = await update($, activityA, a => record(a, { kind: 'edit', at: now }))
  const next = mode(act, now, settings)
  let prev: string | undefined
  await update($, modeA, p => { prev = p; return next })
  if (prev === undefined || prev === next) return
  const t = transition(prev as Mode, next)
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

// RESET: every module cache and timer (pre-flight F3), in one place — a hot reload, a reused
// module or a /clear must start clean. Tasks 13–15 add their own module variables here.
function resetCaches() {
  gitTimer?.cancel()
  gitTimer = null
  git = { branch: null, dirty: [] }
  edited.clear()
  dayText = {}
  retryTimer?.cancel()
  retryTimer = null
  clearParked = false
  unattendedClear = false
  lastWait = null
  lastLightTimer?.cancel()
  lastLightTimer = null
  ttlMs = TTL_1H
}

async function bindSession($: EngineInterface) {
  resetCaches()
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
  submitInstruction($, reason)
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

// Waits in hops of at most an hour; never submits while latched (spec §5); drops the limit
// handover once the resume is sent so a later /clear does not re-inject it.
function scheduleResume($: EngineInterface, at: number) {
  $.clock.after(0, async () => {
    const wait = nextHop(await nowMs($), at)
    if (wait > 0) { $.clock.after(wait, () => { scheduleResume($, at) }); return }
    if (await read($, latchA)) { $.clock.after(60_000, () => { scheduleResume($, at) }); return }
    const pending = await read($, pendingA)
    try {
      await $.prompt.submit({ text: limitResumeText(pending?.path ?? '(no file)') })
    } catch {
      await notify($, V.handoverFailed)
      await log($, 'guard.wait', { reason: 'submit-rejected' })
      return
    }
    if (pending?.reason === 'limit') await savePending($, null)
  })
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

async function barChoice($: EngineInterface, action: 'handover' | 'later' | 'dismiss') {
  await update($, barShownA, () => false)
  if (action === 'dismiss') await update($, barDismissedA, () => true)
  await log($, 'bar', { action })
  if (action === 'handover') await startHandover($, 'request', true)
}

// Does the transcript hold a custom-title line? null = could not tell.
async function sessionNamed($: EngineInterface, transcriptPath: string): Promise<boolean | null> {
  try {
    const r = await $.process.run(['grep', '-c', '-F', '"type":"custom-title"', transcriptPath])
    if (r.exitCode === 0) return Number.parseInt(r.stdout, 10) > 0
    return r.exitCode === 1 ? false : null
  } catch {
    return null
  }
}

// /clear carries an existing name into the new session, so only an unnamed one is renamed.
// Never blocks the resume: a failed rename is a notice, not an error.
async function renameSession($: EngineInterface, name: string | undefined, oldTranscript: string | undefined) {
  if (!name?.trim()) return   // an older stored handover may carry no name
  const named = oldTranscript === undefined ? null : await sessionNamed($, oldTranscript)
  if (named === true) return void (await log($, 'rename', { kept: true }))
  if (named === null) return void (await log($, 'guard.wait', { reason: 'rename-unknown' }))
  await log($, 'rename', { name })
  try {
    await $.command.run({ command: 'rename', args: name })
  } catch {
    await notify($, V.renameFailed)
    await log($, 'guard.wait', { reason: 'rename-rejected' })
  }
}

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

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const r = await next(e)
    await bindSession($)
    await $.command.register({ name: COMMANDS.handover, description: V.cmdHandover })
    await $.command.register({ name: COMMANDS.handoff, description: V.cmdHandover })
    await $.command.register({ name: COMMANDS.setup, description: V.cmdSetup })
    await $.tool.register({ name: TOOL, description: TOOL_DESCRIPTION, inputSchema: INPUT_SCHEMA as unknown as Record<string, unknown> })
    await checkInterlock($)
    const stored = (await $.store.get(pendingKey(session))) as Pending | null | undefined
    if (stored && !(await read($, pendingA))) {
      await update($, pendingA, () => stored)
      await notify($, V.pendingOffer(stored.path))
    }
    scheduleGit($)
    return r
  })

  on('classic.SessionStart', async ($, e, next) => {
    const r = await next(e)
    const repo = await $.session.repo().catch(() => null)
    const watch = repo ? watchPaths(repo.root) : []
    const out = watch.length ? { ...r, watchPaths: [...(r.watchPaths ?? []), ...watch] } : r
    if (e.source !== 'clear') return out
    const pending = await read($, pendingA)
    if (pending) await savePending($, null)         // deletes pending:<old session>
    session = await $.session.id()
    resetCaches()
    scheduleGit($)
    await update($, awaitingA, () => null)
    await update($, deferredA, () => null)
    await update($, lastNudgedA, () => null)
    await update($, barShownA, () => false)
    await update($, barDismissedA, () => false)
    await update($, countdownA, () => null)
    await update($, handoverCountA, () => 0)
    if (!pending) return out
    const follow = pending.followUp
    // /rename starts from its own timer, before the resume submit, and never blocks it.
    const tp = e.transcript_path
    const oldTranscript = tp === undefined ? undefined : `${tp.slice(0, tp.lastIndexOf('/') + 1)}${pending.session}.jsonl`
    $.clock.after(0, () => { void renameSession($, pending.name, oldTranscript) })
    if (follow) $.clock.after(500, () => { void $.prompt.submit({ text: follow, asUser: true }) })
    else if (pending.resume) submitSoon($, resumeText(pending.path), 500)
    await log($, 'resume', { path: pending.path, reason: pending.reason, followUp: follow !== null })
    return { ...out, additionalContext: [...(out.additionalContext ?? []), injectText(pending.markdown)] }
  })

  on('classic.StopFailure', async ($, e, next) => {
    const error = String((e as unknown as { error?: unknown }).error ?? '')
    const usage = await $.session.usage().catch(() => null)
    await setLatch($, latchFromStopFailure(error, usage?.rateLimits ?? [], await nowMs($)))
    return next(e)
  })

  on('classic.FileChanged', async ($, e, next) => {
    scheduleGit($)
    return next(e)
  })

  on('prompt.submit', async ($, e, next) => {
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
    await observe($, { kind: 'prompt', origin: e.origin.kind, at: await nowMs($) })
    if (e.origin.kind !== 'plugin') await cancelCountdown($)
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
    scheduleLastLight($, now, now)
    const awaitingNow = await read($, awaitingA)
    if (awaitingNow?.started) {
      if (awaitingNow.attempts < 2) {
        await update($, awaitingA, () => ({ ...awaitingNow, attempts: awaitingNow.attempts + 1, started: false }))
        submitInstruction($, awaitingNow.reason)
      } else {
        await update($, awaitingA, () => null)
        await notify($, V.handoverFailed)
        await log($, 'guard.wait', { reason: 'tool-not-called' })
      }
    }
    return next(e)
  })

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

  on('session.measure', async ($, e, next) => {
    const pct = e.context.percent ?? null
    await update($, contextA, () => pct)
    const limits = e.rateLimits as RateLimit[]
    await setLatch($, latchFromMeasure(limits))
    await checkLatch($, limits)
    const fired = await read($, firedA)
    const limitDue = earlyStopDue(limits, settings, fired)
    if (limitDue && !(await read($, standDownA))) {
      await update($, firedA, () => [...fired, limitDue.key].slice(-20))
      await log($, 'limit.early_stop', { kind: limitDue.kind, pct: limitDue.pct, resetsAtMs: limitDue.resetsAtMs })
      await notify($, V.earlyStop(limitDue.kind, limitDue.pct, formatHHMM(limitDue.resetsAtMs + RESUME_DELAY_MS)))
      await startHandover($, 'limit', false)
      scheduleResume($, limitDue.resetsAtMs + RESUME_DELAY_MS)
    }
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
    await savePending($, { session, path, name: parsed.fields.session_name, reason, markdown, resume, followUp: null, createdAt: now })
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
}
