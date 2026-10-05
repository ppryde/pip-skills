import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'
import type { Activity, Awaiting, EventKind, Git, Latch, Mode, Pending, PhoneFacts, PendingReason, RateLimit, Settings, StepId } from '../types'
import { COMMANDS, TOOL, TOOL_FULL, classicSessionPath, configRoot, eventsPath, handoverPath } from '../core/name'
import { DEFAULTS, STORE_KEY, loadSettings, pendingKey } from '../core/settings'
import { EMPTY_ACTIVITY, armed, classifyOrigin, mode, onPhone, record, transition } from '../core/arming'
import type { Signal } from '../core/arming'
import { appendLine, dayKey, makeRecord } from '../core/eventlog'
import { COALESCE_MS, GIT_ARGV, parseGit, touchesGit, watchPaths } from '../core/git'
import { INPUT_SCHEMA, TOOL_DESCRIPTION, grownEnough, injectText, instructionText, limitResumeText, nextThreshold, parseFields, renderHandover, resumeText, reusable } from '../core/handover'
import { TAIL_CMD, type CacheTtl, parseWrites, transcriptPathFor, ttlFromWrites } from '../core/cache-ttl'
import { TTL_1H, fireAt, holdOnReturn, rearm, shouldFire } from '../core/last-light'
import { clearGate, needsRcQuestion } from '../core/surfaces'
import { applyAnswers, extractAnswers, isStep, nextCard, questionFor, stepForQuestion } from '../core/setup'
import { RESUME_DELAY_MS, earlyStopDue, formatHHMM, latchCleared, latchFromMeasure, latchFromStopFailure, nextHop } from '../core/limits'
import { classicHooksInstalled } from '../core/interlock'
import { V } from '../core/voice'
import type { WaitReason } from '../core/voice'

// The effectful shell: the ONLY file that touches `$`. Decisions live in ../core.

// $.state is per session and every /clear wipes it (PROBES §9): these atoms hold only what a
// fresh session may forget.
const modeA = atom({ plugin: 'context-vigil-mod', key: 'mode' } as const, 'idle')
const contextA = atom({ plugin: 'context-vigil-mod', key: 'contextPct' } as const, null)
const baselineA = atom({ plugin: 'context-vigil-mod', key: 'baselinePct' } as const, null as number | null)
const lastNudgedA = atom({ plugin: 'context-vigil-mod', key: 'lastNudged' } as const, null)
const barShownA = atom({ plugin: 'context-vigil-mod', key: 'barShown' } as const, false)
const barDismissedA = atom({ plugin: 'context-vigil-mod', key: 'barDismissed' } as const, false)
const pendingA = atom({ plugin: 'context-vigil-mod', key: 'pending' } as const, null)
const countdownA = atom({ plugin: 'context-vigil-mod', key: 'countdownEndsAt' } as const, null)
const transcriptA = atom({ plugin: 'context-vigil-mod', key: 'transcriptPath' } as const, null as string | null)
// Information only (PROBES §11): what the session's cache is. The fire-time check stays the gate.
const cacheTtlA = atom({ plugin: 'context-vigil-mod', key: 'cacheTtl' } as const, 'unknown' as CacheTtl)
const ttlReadA = atom({ plugin: 'context-vigil-mod', key: 'ttlRead' } as const, false)
const ttlInfoDismissedA = atom({ plugin: 'context-vigil-mod', key: 'ttlInfoDismissed' } as const, false)
const lastApiA = atom({ plugin: 'context-vigil-mod', key: 'lastApiAt' } as const, null)
const awaitingA = atom({ plugin: 'context-vigil-mod', key: 'awaiting' } as const, null as Awaiting | null)
const deferredA = atom({ plugin: 'context-vigil-mod', key: 'deferred' } as const, null as Awaiting | null)
const handoverCountA = atom({ plugin: 'context-vigil-mod', key: 'handoverCount' } as const, 0)
// The phone facts of `activity`, written through so a hot reload (which keeps $.state) restores
// them; a clear wipes this, so the clear branch writes it again from the module copy.
const phoneA = atom({ plugin: 'context-vigil-mod', key: 'phoneFacts' } as const, null as PhoneFacts | null)

// An account fact in $.store: the limit latch, shared by every session of the account.
const LATCH_KEY = 'latch'

// Facts about the person and the install that a /clear must not forget: module variables
// survive it (same process). A new session or a hot reload (bindSession) starts them fresh,
// counting that moment as the person being here for one idle window.
let activity: Activity = EMPTY_ACTIVITY
let lastLightArmed = false
let standDown = false
// Per process, never reset: each running session owes its own early stop before a hard limit,
// and a clear (new session id) must not re-fire one for the same window. A reload may re-fire once.
let firedEarlyStops: string[] = []
// The limit resume waiting on its handover file; the tool call fills `path` when it is written.
let limitResume: { path: string | null } | null = null
// The first-RC question is asked once per process: a clear wipes $.state, so it cannot live there.
// A new session (bindSession) starts it fresh; resetCaches leaves it alone.
let rcAsked = false

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
let setupRun: { only: string | undefined; asked: StepId[] } | null = null
let lastLightTimer: { cancel: () => void } | null = null
let countdownTick: { cancel: () => void } | null = null

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
function submitSoon($: EngineInterface, prompt: { text: string; asUser?: true }, delayMs = 0, onSent?: () => void, onFailed?: () => void) {
  $.clock.after(delayMs, () => { void $.prompt.submit(prompt).then(() => onSent?.(), () => onFailed?.()) })
}

// A resume or held-prompt submit that is refused: say so, with the handover and the held text.
async function resumeFailed($: EngineInterface, path: string | null, held: string | null) {
  await notify($, V.resumeFailed(path, held))
  await log($, 'guard.wait', { reason: 'resume-rejected', path, held: held !== null })
}

// PROBES.md §7: a mod never sees its own submit in prompt.submit, so `started` is marked here.
function submitInstruction($: EngineInterface, reason: PendingReason) {
  submitSoon($, { text: instructionText(reason) }, 0, () => {
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
  activity = record(activity, signal)
  if (signal.kind === 'prompt' && classifyOrigin(signal.origin) === 'human') await savePhoneFacts($)
  // R1-09: an explicit act from the person cancels a handover that waited on the latch.
  if ((signal.kind === 'human-command' || (signal.kind === 'prompt' && classifyOrigin(signal.origin) === 'human')) && (await read($, deferredA))) {
    const dropped = await read($, deferredA)
    await update($, deferredA, () => null)
    await notify($, V.deferredDropped)
    await log($, 'guard.wait', { reason: 'deferred-dropped', deferred: dropped?.reason })
  }
  // Spec §2: a non-empty draft in the terminal box is you being here.
  if (signal.kind === 'agent-step' && (await $.prompt.read()).text.trim()) activity = record(activity, { kind: 'edit', at: now })
  const act = activity   // this observation's view: later awaits may move `activity` on
  const next = mode(act, now, settings)
  let prev: string | undefined
  await update($, modeA, p => { prev = p; return next })
  if (prev === undefined || prev === next) return
  const t = transition(prev as Mode, next)
  if (t && settings.auto) {
    await log($, t, { from: prev, to: next, idleMs: act.lastHumanAt === null ? null : now - act.lastHumanAt, origin: act.lastHumanOrigin })
  }
  if (t === 'arm') await maybeAskRc($)
}

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
  submitSoon($, { text: cardPrompt(ids.map(id => questionFor(id))) })
}

// Spec §2 / pre-flight F24: asked when auto mode would first arm on the phone.
async function maybeAskRc($: EngineInterface) {
  if (!needsRcQuestion(onPhone(activity), settings.rcAutoClear, settings.auto)) return
  if (setupRun || rcAsked) return
  rcAsked = true
  await notify($, V.rcAsk)
  await log($, 'rc.answer', { asked: true })
  await startSetup($, 'rc')
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
  setupRun = null
  countdownTick?.cancel()
  countdownTick = null
}

async function savePhoneFacts($: EngineInterface) {
  const { lastHumanOrigin, lastBridgeAt } = activity
  await update($, phoneA, () => ({ lastHumanOrigin, lastBridgeAt }))
}

async function bindSession($: EngineInterface) {
  resetCaches()
  // A reload keeps $.state: the phone facts come back so the RC gate still sees the phone.
  activity = { ...EMPTY_ACTIVITY, ...(await read($, phoneA)), lastHumanAt: await nowMs($) }
  lastLightArmed = false
  standDown = false
  rcAsked = false
  root = configRoot({ CLAUDE_CONFIG_DIR: await $.env.get('CLAUDE_CONFIG_DIR'), HOME: await $.env.get('HOME') })
  session = await $.session.id()
  cwd = await $.session.cwd()
  settings = loadSettings(await $.store.get(STORE_KEY))
}

async function checkInterlock($: EngineInterface) {
  const text = await $.fs.read(`${root}/settings.json`).then(t => String(t)).catch(() => null)
  const record = await $.fs.exists(classicSessionPath(root, session)).catch(() => false)
  const classic = classicHooksInstalled(text) || record
  const was = standDown
  standDown = classic
  if (classic && !was) {
    await notify($, V.classicActive)
    await log($, 'standdown', { settingsHooks: classicHooksInstalled(text), sessionRecord: record })
  }
}

async function readLatch($: EngineInterface): Promise<Latch> {
  return ((await $.store.get(LATCH_KEY)) as Latch | undefined) ?? null
}

async function savePending($: EngineInterface, p: Pending | null) {
  const prev = await read($, pendingA)
  await update($, pendingA, () => p)
  if (p) await $.store.set(pendingKey(p.session), p)
  else await $.store.delete(pendingKey(prev?.session ?? session))
}

async function startHandover($: EngineInterface, reason: PendingReason, resume: boolean, unattended: boolean = reason === 'threshold') {
  if (standDown) return
  if (await readLatch($)) {
    // Spec §5: while latched the mod never submits; Task 14's checkLatch starts it later.
    await update($, deferredA, () => ({ reason, resume, attempts: 1, started: false, unattended }))
    await notify($, V.waiting('latched'))
    await log($, 'guard.wait', { reason: 'latched', deferred: reason })
    return
  }
  const pending = await read($, pendingA)
  if ((reason === 'threshold' || reason === 'request') && reusable(pending, await read($, lastApiA))) {
    scheduleClear($, unattended)
    return
  }
  if (pending) await supersedePending($)
  await update($, awaitingA, () => ({ reason, resume, attempts: 1, started: false, unattended }))
  await log($, 'handover.requested', { reason, resume })
  submitInstruction($, reason)
}

// A stale pending handover gives way to the fresh one: its clear stops waiting and a /clear
// in between injects nothing old. The file stays on disk.
async function supersedePending($: EngineInterface) {
  retryTimer?.cancel()
  retryTimer = null
  clearParked = false
  lastWait = null
  await setCountdown($, null)
  await savePending($, null)
}

// The band draws the seconds left from the clock, which never redraws it: tick while it runs.
async function setCountdown($: EngineInterface, endsAt: number | null) {
  await update($, countdownA, () => endsAt)
  countdownTick?.cancel()
  countdownTick = endsAt === null ? null : $.clock.every(1000, () => { $.ui.invalidate('ui.render') })
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
  // An unattended clear is only for an unattended session: re-checked here, not just when it began.
  if (unattendedClear && mode(activity, now, settings) === 'attended') {
    await setCountdown($, null)
    lastWait = null
    clearParked = true
    await notify($, V.clearSkippedAttended)
    await log($, 'clear.skipped', { reason: 'attended' })
    return
  }
  const gate = clearGate({
    now, draft: (await $.prompt.read()).text, onPhone: onPhone(activity), lastBridgeAt: activity.lastBridgeAt,
    rcAutoClear: settings.rcAutoClear, latched: (await readLatch($)) !== null,
    countdownEndsAt: await read($, countdownA), classicActive: standDown, unattended: unattendedClear,
  })
  if (gate.go) {
    lastWait = null
    await setCountdown($, null)
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
  if (gate.reason === 'countdown-start') await setCountdown($, now + (gate.recheckMs ?? 0))
  if (gate.recheckMs === null) { clearParked = true; return }
  retryTimer = $.clock.after(gate.recheckMs, () => { void tryClear($) })
}

async function setLatch($: EngineInterface, l: Latch) {
  if (!l || (await readLatch($))) return
  await $.store.set(LATCH_KEY, l)
  await log($, 'limit.latched', { kind: l.kind, resetsAtMs: l.resetsAtMs })
  await notify($, V.limitLatched(formatHHMM(l.resetsAtMs)))
  const now = await nowMs($)
  $.clock.after(Math.max(0, l.resetsAtMs - now) + 1000, () => { void checkLatch($, []) })
}

// The latch is account-wide: another session may lift it (delete the key) and drain only its
// own work, so an absent latch drains this session's deferred handover too.
async function checkLatch($: EngineInterface, limits: RateLimit[]) {
  const l = await readLatch($)
  if (l) {
    if (!latchCleared(l, await nowMs($), limits)) return
    await $.store.delete(LATCH_KEY)
    await log($, 'limit.cleared', { kind: l.kind })
    await notify($, V.limitCleared)
  }
  const deferred = await read($, deferredA)
  if (deferred) {
    await update($, deferredA, () => null)
    // R1-09: hours later the person may be anywhere. A threshold or request runs only if auto mode
    // is on and they are not attended, and then as an unattended handover (attended re-check, RC
    // gate). A last light should not get here (shouldFire refuses under a latch); drop it quietly.
    if (deferred.reason === 'limit') await startHandover($, deferred.reason, deferred.resume, false)
    else if (deferred.reason !== 'last_light' && settings.auto && mode(activity, await nowMs($), settings) !== 'attended') {
      await startHandover($, deferred.reason, deferred.resume, true)
    } else {
      if (deferred.reason !== 'last_light') await notify($, V.deferredDropped)
      await log($, 'guard.wait', { reason: 'deferred-dropped', deferred: deferred.reason })
    }
    return
  }
  // Only a clear the latch parked: one parked for a cancelled countdown or a refusal stays put.
  if (clearParked && lastWait === 'latched' && (await read($, pendingA))) scheduleClear($, unattendedClear)
}

// Waits in hops of at most an hour; never submits while latched (spec §5); drops the limit
// handover once the resume is sent so a later /clear does not re-inject it. The path comes from
// `job`, so a clear that consumed the pending handover in between still names the file.
function scheduleResume($: EngineInterface, at: number, job: { path: string | null } = { path: null }) {
  limitResume = job
  $.clock.after(0, async () => {
    const wait = nextHop(await nowMs($), at)
    if (wait > 0) { $.clock.after(wait, () => { scheduleResume($, at, job) }); return }
    if (await readLatch($)) { $.clock.after(60_000, () => { scheduleResume($, at, job) }); return }
    const pending = await read($, pendingA)
    try {
      await $.prompt.submit({ text: limitResumeText(job.path ?? pending?.path ?? '(no file)') })
    } catch {
      await notify($, V.resumeFailed(job.path ?? pending?.path ?? null, null))
      await log($, 'guard.wait', { reason: 'submit-rejected' })
      return
    }
    if (pending?.reason === 'limit') await savePending($, null)
  })
}

async function cancelCountdown($: EngineInterface) {
  if ((await read($, countdownA)) === null) return
  await setCountdown($, null)
  retryTimer?.cancel()
  retryTimer = null
  clearParked = true
  lastWait = null
  await notify($, V.countdownCancelled)
  await log($, 'guard.wait', { reason: 'countdown-cancelled' })
}

async function showNudge($: EngineInterface, pct: number) {
  if (settings.bar && !onPhone(activity)) {
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
  if (now >= lastApiAt + TTL_1H) return   // no fire for a cache that is already cold
  lastLightTimer = $.clock.after(Math.max(0, fireAt(lastApiAt) - now), () => { void maybeFireLastLight($) })
}

// The one place the cache lifetime is asked (PROBES §11): scheduling assumed 1 hour, the latest
// write in the transcript's tail says whether that held. Nothing found is no fire; no retry.
async function readTtl($: EngineInterface): Promise<CacheTtl> {
  let writes = null
  try {
    const path = (await read($, transcriptA)) ?? transcriptPathFor(root, await $.session.cwd(), await $.session.id())
    const r = await $.process.run(['sh', '-c', TAIL_CMD, 'sh', path])
    if (r.exitCode === 0) writes = parseWrites(r.stdout)
  } catch { /* unknown */ }
  return ttlFromWrites(writes)
}

async function cacheIsOneHour($: EngineInterface): Promise<boolean> {
  const ttl = await readTtl($)
  if (ttl !== '1h') await log($, 'last_light.skip', { reason: `ttl-${ttl}` })
  return ttl === '1h'
}

async function setCacheTtl($: EngineInterface, to: CacheTtl, source: 'response' | 'switch') {
  const from = await read($, cacheTtlA)
  if (to === from) return
  await update($, cacheTtlA, () => to)
  if (!settings.lastLight) return
  if (to === '5m') await log($, 'last_light.off', { ttl: to, source })
  else if (from === '5m' && to === '1h') {
    await log($, 'last_light.on', { ttl: to, source })
    await notify($, V.lastLightBackOn)
  }
}

// The session's first response that wrote to the cache: one detached tail read, never again.
async function learnSessionTtl($: EngineInterface) {
  await setCacheTtl($, await readTtl($), 'response')
}

async function maybeFireLastLight($: EngineInterface) {
  lastLightTimer = null
  const now = await nowMs($)
  await observe($, { kind: 'agent-step', at: activity.lastAgentAt ?? 0 })  // picks up a draft (spec §2)
  const verdict = shouldFire({
    enabled: settings.lastLight, mode: mode(activity, now, settings),
    contextPct: await read($, contextA), threshold: settings.lastLightAt,
    pending: (await read($, pendingA)) !== null, latched: (await readLatch($)) !== null,
    armed: lastLightArmed,
  })
  if (!verdict.fire) return
  if (!(await cacheIsOneHour($))) return
  lastLightArmed = false
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
  submitSoon($, { text: held, asUser: true }, 0, undefined, () => { void resumeFailed($, pending?.path ?? null, held) })
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
    await checkLatch($, [])   // a latch another process left behind and never lifted
    const stored = (await $.store.get(pendingKey(session))) as Pending | null | undefined
    const live = await read($, pendingA)
    if (stored && !live) {
      await update($, pendingA, () => stored)
      await notify($, V.pendingOffer(stored.path))
    } else if (live) {
      // A hot reload: $.state kept the pending handover but its clear's timers are gone. The
      // reload also forgot the phone, so only a clear the person asked for is picked back up;
      // an unattended one is offered, never run past an RC answer or a countdown it can't see.
      await setCountdown($, null)
      if (live.reason === 'request' && reusable(live, await read($, lastApiA))) scheduleClear($, false)
      else await notify($, V.pendingOffer(live.path))
    }
    // A reload counts as the person being here (bindSession): it re-arms last light too, and
    // the fire the reload's dropped timer owed is scheduled again from the last turn.
    const lastApi = await read($, lastApiA)
    if (lastApi !== null) {
      lastLightArmed = true
      scheduleLastLight($, lastApi, await nowMs($))
    }
    scheduleGit($)
    return r
  })

  on('classic.SessionStart', async ($, e, next) => {
    const r = await next(e)
    const repo = await $.session.repo().catch(() => null)
    const watch = repo ? watchPaths(repo.root) : []
    const out = watch.length ? { ...r, watchPaths: [...(r.watchPaths ?? []), ...watch] } : r
    if (e.transcript_path) await update($, transcriptA, () => e.transcript_path ?? null)
    if (e.source !== 'clear') return out
    // PROBES §9: $.state is already wiped here, so the handover comes from $.store, keyed by
    // `session` — still the pre-clear id until it is rebound below.
    const pending = ((await $.store.get(pendingKey(session))) as Pending | null | undefined) ?? null
    if (pending) await $.store.delete(pendingKey(session))
    session = await $.session.id()
    resetCaches()
    scheduleGit($)
    // The wipe already empties these; reset anyway so the clear never leans on it.
    await update($, awaitingA, () => null)
    await update($, deferredA, () => null)
    await update($, lastNudgedA, () => null)
    await update($, baselineA, () => null)
    await update($, barShownA, () => false)
    await update($, barDismissedA, () => false)
    await update($, countdownA, () => null)
    await update($, handoverCountA, () => 0)
    await update($, cacheTtlA, () => 'unknown')
    await update($, ttlReadA, () => false)
    await update($, ttlInfoDismissedA, () => false)
    if (activity.lastHumanOrigin !== null) await savePhoneFacts($)   // the wipe took them; a later reload needs them
    if (!pending) return out
    const follow = pending.followUp
    // /rename starts from its own timer, before the resume submit, and never blocks it.
    const tp = e.transcript_path
    const oldTranscript = tp === undefined ? undefined : `${tp.slice(0, tp.lastIndexOf('/') + 1)}${pending.session}.jsonl`
    $.clock.after(0, () => { void renameSession($, pending.name, oldTranscript) })
    if (follow) submitSoon($, { text: follow, asUser: true }, 500, undefined, () => { void resumeFailed($, pending.path, follow) })
    else if (pending.resume) submitSoon($, { text: resumeText(pending.path) }, 500, undefined, () => { void resumeFailed($, pending.path, null) })
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
    if (rearm(lastLightArmed, e.origin.kind)) lastLightArmed = true
    const pending = await read($, pendingA)
    const lastApi = await read($, lastApiA)
    if (holdOnReturn({ pendingIsLastLight: pending?.reason === 'last_light', origin: e.origin.kind, now, cacheExpiresAt: lastApi === null ? null : lastApi + TTL_1H })) {
      await observe($, { kind: 'prompt', origin: e.origin.kind, at: now })
      const held = e.text
      $.clock.after(0, () => { void askReturn($, held) })
      return { drop: V.heldForLastLight }
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
    if (e.agentId === undefined && (e.usage?.cache_creation_input_tokens ?? 0) > 0 && !(await read($, ttlReadA))) {
      await update($, ttlReadA, () => true)
      $.clock.after(0, () => { void learnSessionTtl($) })
    }
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

  // Only the Post event: Pre is ambiguous (the cache left or the one entered).
  on('classic.PostModelSwitch', async ($, e, next) => {
    const label = (e as unknown as { cache_ttl?: unknown }).cache_ttl
    if (label === '1h' || label === '5m') await setCacheTtl($, label, 'switch')
    return next(e)
  })

  on('session.measure', async ($, e, next) => {
    const pct = e.context.percent ?? null
    const prevPct = await read($, contextA)
    await update($, contextA, () => pct)
    if (pct !== null && (await read($, baselineA)) === null) await update($, baselineA, () => pct)
    const limits = e.rateLimits as RateLimit[]
    await setLatch($, latchFromMeasure(limits))
    await checkLatch($, limits)
    const limitDue = earlyStopDue(limits, settings, firedEarlyStops)
    if (limitDue && !standDown) {
      firedEarlyStops = [...firedEarlyStops, limitDue.key].slice(-20)
      await log($, 'limit.early_stop', { kind: limitDue.kind, pct: limitDue.pct, resetsAtMs: limitDue.resetsAtMs })
      await notify($, V.earlyStop(limitDue.kind, limitDue.pct, formatHHMM(limitDue.resetsAtMs + RESUME_DELAY_MS)))
      await startHandover($, 'limit', false)
      scheduleResume($, limitDue.resetsAtMs + RESUME_DELAY_MS)
    }
    if (pct !== null && !standDown) {
      const due = nextThreshold(pct, settings, await read($, lastNudgedA))
      if (due !== null) {
        const now = await nowMs($)
        const unattended = armed(activity, now, settings)
        const baseline = await read($, baselineA)
        if (unattended && !grownEnough(pct, baseline, settings.step)) {
          // Held back, not spent: the step stays due until the growth is there.
          if (pct !== prevPct) await log($, 'guard.baseline', { pct, baseline })
        } else {
          await update($, lastNudgedA, () => due)
          await log($, 'threshold', { pct, step: due, mode: await read($, modeA) })
          if (unattended) await startHandover($, 'threshold', true)
          else await showNudge($, pct)
        }
      }
    }
    return next(e)
  })

  on('command.run', { command: COMMANDS.setup }, async ($, e) => {
    await startSetup($, ((e as unknown as { args?: string }).args ?? '').trim() || undefined)
    return { text: V.settingUp }
  })

  on('tool.call', { tool: 'AskUserQuestion' } as never, async ($, e, next) => {
    const r = await next(e) as { context?: string[] }
    // Captured once: a clear landing during an await below resets the module's setupRun.
    const run = setupRun
    if (!run) return r as never
    const pairs = Object.entries(extractAnswers(e, r))
      .map(([q, answer]) => ({ step: stepForQuestion(q), answer }))
      .filter((p): p is { step: StepId; answer: string } => p.step !== undefined)
    if (!pairs.length) return r as never
    const applied = applyAnswers(settings, pairs)
    settings = applied.settings
    await $.store.set(STORE_KEY, settings)
    await log($, 'setup', { steps: pairs.map(p => p.step), retell: applied.retell })
    if (pairs.some(p => p.step === 'rc')) await log($, 'rc.answer', { answer: settings.rcAutoClear })
    const more = (prompt: string) => ({ ...r, context: [...(r.context ?? []), prompt] }) as never
    if (applied.retell.length) return more(cardPrompt(applied.retell.map(id => questionFor(id, true))))
    const ids = nextCard(settings, run.asked, run.only)
    if (ids.length) {
      run.asked.push(...ids)
      return more(cardPrompt(ids.map(id => questionFor(id))))
    }
    if (setupRun === run) setupRun = null
    await notify($, V.setupSaved)
    if (settings.rcAutoClear === 'yes' && clearParked && (await read($, pendingA))) scheduleClear($, true)
    return r as never
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
    // Only a handover the mod asked for may end in a clear; a call with no `awaiting` is the
    // model volunteering (or repeating itself): save it, offer it, never clear (R1-01).
    const requested = awaiting !== null
    const reason = awaiting?.reason ?? 'request'
    const resume = awaiting?.resume ?? false
    await update($, awaitingA, () => null)
    const n = (await read($, handoverCountA)) + 1
    await update($, handoverCountA, () => n)
    const path = handoverPath(root, session, n)
    const now = await nowMs($)
    const markdown = renderHandover(parsed.fields, {
      session, at: new Date(now).toISOString(), cwd, branch: git.branch, dirty: git.dirty,
      edited: [...edited], contextPct: await read($, contextA),
    })
    try {
      await $.fs.write(path, markdown)
    } catch (err) {
      await notify($, V.handoverFailed)
      await log($, 'guard.wait', { reason: 'write-failed', path, error: String(err) })
      return { result: `Handover not saved: writing ${path} failed (${String(err)}). Nothing was cleared; tell the person.` } as never
    }
    await savePending($, { session, path, name: parsed.fields.session_name, reason, markdown, resume, followUp: null, createdAt: now })
    if (reason === 'limit' && limitResume) limitResume.path = path
    await log($, 'handover.written', { reason, bytes: markdown.length, path })
    if (!requested) {
      await notify($, V.handoverUnrequested(path))
      await log($, 'guard.wait', { reason: 'unrequested', path })
      return { result: `Saved handover to ${path} (not requested by context-vigil-mod; nothing was cleared)` } as never
    }
    await notify($, reason === 'last_light' ? V.lastLightReady : V.handoverSaved(path))
    if (reason === 'threshold' || reason === 'request') scheduleClear($, awaiting?.unattended ?? false)
    return { result: `Saved handover to ${path}` } as never
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)
    if (standDown) return next(e)
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
    if (!settings.bar || !(await read($, barShownA))) {
      // The threshold bar wins; otherwise the one quiet fact: last light is off for this cache.
      if (!settings.lastLight || (await read($, cacheTtlA)) !== '5m' || (await read($, ttlInfoDismissedA))) return next(e)
      return (
        <Box>
          <Text>{V.lastLightOff}   </Text>
          <Button key="dismiss-ttl" hotkey="0" plain label={V.barDismiss} onPress={() => update($, ttlInfoDismissedA, () => true)} />
        </Box>
      )
    }
    const pct = (await read($, contextA)) ?? 0
    const step = (await read($, lastNudgedA)) ?? settings.nudgeAt
    const latch = await readLatch($)
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
