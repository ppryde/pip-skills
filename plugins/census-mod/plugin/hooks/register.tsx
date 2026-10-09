import type { EngineInterface, Register, Timer } from 'claude-code'
import { COUNTER_KEEP_MS, EMPTY_COUNTERS, STORE_PREFIX, TAIL_CMD, addTurn, compacted, counterKey, DEFAULT_TTL, expiresAtMs, isWarm, parseWrites, ttlFromWrites, ttlMs, withTtl } from '../core/cache'
import { INGEST_TIMEOUT_MS, WHICH_ARGV, censusDir, findSibling, delayFor, endTimeoutMs, ingestArgv, ingestEnv, pointerFiles } from '../core/census'
import type { CensusEnv } from '../core/census'
import { GH_TIMEOUT_MS, ghArgv, ghKey, parsePrList, shouldRefresh, touchesPr } from '../core/gh'
import type { GhEntry, Why } from '../core/gh'
import { COALESCE_MS as GIT_COALESCE_MS, GIT_DIR_ARGV, GIT_STATUS_ARGV, parseStatus, touchesGit, watchPaths, worktreeOf } from '../core/git'
import { configRoot, transcriptPathFor } from '../core/name'
import { buildPayload, modelOf, rateLimitsOf } from '../core/payload'
import type { Event } from '../core/payload'
import { TITLE_ARGV, TITLE_TAIL_CMD, findProc, lastTitle } from '../core/registry'
import { TONE_COLOR, draw, fit } from '../core/render'
import { BACKUP_FILE, backupBlocks, placementFrom, replaceFrom, L, MIN_CENSUS, NO_DETECTION, PRESETS, Q, SETUP_KEY, atLeast, commandIsCensus, effective, hasIngestBlock, parseSettings, presetFrom, recordFrom, removeStatusLine, restoreStatusLine, scriptCandidates, settingsTmp, statusLineCommand, writerActive, writersFrom, is } from '../core/setup'
import type { Detection, Effective, Saved } from '../core/setup'
import type { Line, RenderEnv, RenderInput } from '../core/render'
import type { Counters, RateLimit, Snap } from '../core/types'

// The effectful shell: the ONLY file that touches `$`. Decisions live in ../core.
//
// State is module variables plus $.store (counters, gh cache): a hot reload loses the variables, and
// session.start (which re-fires on a reload) rebuilds them. Nothing is kept in $.state, so a /clear
// has nothing to wipe and classic.SessionStart(clear) simply binds the new session.

type Env = CensusEnv & RenderEnv & { USERPROFILE?: string; CENSUS_MOD_PLACEMENT?: string }

let env: Env = {} // what the mod runs on: the environment, then the answers laid over it
let rawEnv: Env = {} // the environment alone: it outranks an answer
let saved: Saved = {}
let det: Detection = NO_DETECTION
let eff: Effective = effective({}, {}, NO_DETECTION, null)
let setupRun: object | null = null
const titleScanned = new WeakMap<Snap, string>() // snapshot -> the transcript path whose whole file was scanned
let offerTimer: Timer | null = null
let interactive: boolean | null = null
let snap: Snap | null = null
let hydrating: Promise<void> | null = null
let gitReady: Promise<void> | null = null // the first `git status` of the bound session, so the first write carries it
let gitReadyDone: (() => void) | null = null
const ended = new Set<string>()
let lastActiveAt: number | null = null
let limitsKey = ''
let ingestTimer: Timer | null = null
let lastIngestAt: number | null = null
let pending: Event | null = null
let coldTimer: Timer | null = null
let tickTimer: Timer | null = null
let gitTimer: Timer | null = null
let lastGitAt: number | null = null
let cli: string | null | undefined
let cliLookedAt = 0
let saidNoCli = false
let saidNoGh = false

const TICK_MS = 30_000
const CLI_RETRY_MS = 60_000

async function nowMs($: EngineInterface): Promise<number> {
  return $.clock.now()
}

async function loadEnv($: EngineInterface): Promise<Env> {
  return {
    CENSUS_MOD_STORE: await $.env.get('CENSUS_MOD_STORE'),
    CENSUS_STORE: await $.env.get('CENSUS_STORE'),
    CENSUS_CLI: await $.env.get('CENSUS_CLI'),
    CLAUDE_CONFIG_DIR: await $.env.get('CLAUDE_CONFIG_DIR'),
    HOME: await $.env.get('HOME'),
    USERPROFILE: await $.env.get('USERPROFILE'),
    CENSUS_STATUSLINE_SEGMENTS: await $.env.get('CENSUS_STATUSLINE_SEGMENTS'),
    CENSUS_MOD_PLACEMENT: await $.env.get('CENSUS_MOD_PLACEMENT'),
    CENSUS_STATUSLINE_MASCOT: await $.env.get('CENSUS_STATUSLINE_MASCOT'),
    CLAUDE_COST_BUDGET: await $.env.get('CLAUDE_COST_BUDGET'),
    CLAUDE_PROFILE: await $.env.get('CLAUDE_PROFILE'),
  }
}

function fresh(id: string, cwd: string): Snap {
  return {
    sessionId: id, transcriptPath: null, cwd, worktreePath: null, version: null, model: null, sessionName: null,
    ctxPct: null, ctxWindow: null, costUsd: null, startedAt: null, rateLimits: [],
    counters: EMPTY_COUNTERS, ttl: DEFAULT_TTL, git: null, pr: null, proc: null,
  }
}

const repaint = ($: EngineInterface) => void $.ui.invalidate('ui.render')

// ---- engine facts -------------------------------------------------------------------------

async function refreshEngine($: EngineInterface) {
  if (!snap) return
  const usage = await $.session.usage().catch(() => null)
  if (usage) {
    snap.ctxPct = usage.context.percent ?? null
    snap.ctxWindow = usage.context.window ?? null
    snap.costUsd = usage.cost?.usd ?? null
    snap.startedAt = usage.startedAt
    snap.rateLimits = usage.rateLimits as RateLimit[]
    limitsKey = limitsFingerprint(snap.rateLimits)
  }
  const model = await $.session.model().catch(() => null)
  if (model) snap.model = modelOf(model)
}

const limitsFingerprint = (l: RateLimit[]): string => l.map(x => `${x.kind}:${x.percentUsed}:${x.resetsAt ?? ''}`).sort().join('|')

async function locateProc($: EngineInterface) {
  if (!snap || snap.proc) return // looked for again on every write until found: it is one small read
  try {
    const root = configRoot(env)
    if (!root) return
    const entries = await $.fs.list(`${root}/sessions`)
    const files: { text: string }[] = []
    for (const f of entries) {
      if (!f.name.endsWith('.json')) continue
      const text = await $.fs.read(`${root}/sessions/${f.name}`).catch(() => undefined)
      if (typeof text === 'string') files.push({ text })
    }
    const proc = findProc(files, snap.sessionId)
    if (proc) {
      snap.proc = proc
      snap.version = proc.version ?? snap.version
    }
  } catch {
    // the registry is a nicety for liveness; recording goes on without it
  }
}

/**
 * The session's title from its transcript. Whole file once (at bind); after that only the tail, where a later
 * /rename lands, so a long session is not re-read end to end on every turn. Applied to `s`, the snapshot the
 * read was asked for, never to whatever the module holds by the time the read returns.
 */
async function readName($: EngineInterface, s: Snap | null = snap, whole = false) {
  if (!s?.transcriptPath) return
  try {
    const argv = whole ? TITLE_ARGV(s.transcriptPath) : ['sh', '-c', TITLE_TAIL_CMD, 'sh', s.transcriptPath]
    const r = await $.process.run(argv)
    if (r.exitCode === 0) s.sessionName = lastTitle(r.stdout) ?? s.sessionName
  } catch {
    // keep the last name
  }
}

async function readTtl($: EngineInterface, s: Snap | null = snap) {
  if (!s?.transcriptPath) return
  try {
    const r = await $.process.run(['sh', '-c', TAIL_CMD, 'sh', s.transcriptPath])
    const found = r.exitCode === 0 ? ttlFromWrites(parseWrites(r.stdout)) : null
    if (found) {
      s.ttl = found
      s.counters = withTtl(s.counters, found)
    }
  } catch {
    // keep the last known (default 5m)
  }
}

// ---- counters (survive a reload or restart) ------------------------------------------------

async function loadCounters($: EngineInterface, id: string): Promise<Counters> {
  const stored = (await $.store.get(counterKey(id)).catch(() => undefined)) as Counters | undefined
  return stored && typeof stored.requests === 'number' ? { ...EMPTY_COUNTERS, ...stored } : EMPTY_COUNTERS
}

async function saveCounters($: EngineInterface, s: Snap | null = snap) {
  if (s) await $.store.set(counterKey(s.sessionId), s.counters).catch(() => undefined)
}

async function pruneCounters($: EngineInterface, keep: string, now: number) {
  try {
    for (const key of await $.store.keys()) {
      if (!key.startsWith(STORE_PREFIX) || key === counterKey(keep)) continue
      const c = (await $.store.get(key)) as Counters | undefined
      if (!c || now - (c.updatedAt ?? 0) > COUNTER_KEEP_MS) await $.store.delete(key)
    }
  } catch {
    // housekeeping only
  }
}

// ---- recording -----------------------------------------------------------------------------

async function discover($: EngineInterface): Promise<string | null> {
  const now = await nowMs($)
  if (cli) return cli
  if (cli === null && now - cliLookedAt < CLI_RETRY_MS) return null
  cliLookedAt = now
  cli = null
  for (const pointer of pointerFiles(env)) {
    const text = await $.fs.read(pointer).catch(() => undefined)
    const path = typeof text === 'string' ? text.trim() : ''
    if (path && (await $.fs.exists(path).catch(() => false))) return (cli = path)
  }
  if (env.CENSUS_CLI && (await $.fs.exists(env.CENSUS_CLI).catch(() => false))) return (cli = env.CENSUS_CLI)
  const sibling = await siblingCli($)
  if (sibling) return (cli = sibling)
  const which = await $.process.run(WHICH_ARGV).catch(() => undefined)
  const found = which?.exitCode === 0 ? which.stdout.trim() : ''
  if (found) return (cli = found)
  if (!saidNoCli) {
    saidNoCli = true
    $.ui.log('census not found — install the census plugin (the band is drawn, nothing is recorded)')
  }
  return null
}

async function siblingCli($: EngineInterface): Promise<string | null> {
  let root: string | undefined
  try {
    root = $.plugin.root
  } catch {
    return null
  }
  if (!root) return null
  return findSibling({ exists: p => $.fs.exists(p), list: p => $.fs.list(p) }, root)
}

async function ingest($: EngineInterface, event: Event, endedReason?: string, timeoutMs = INGEST_TIMEOUT_MS, of: Snap | null = snap) {
  if (!of) return
  if (eff.record === 'no') return
  const path = await discover($)
  if (!path) return
  const payload = buildPayload(of, await nowMs($), event, endedReason)
  try {
    const out = await $.process.run(ingestArgv(path), { stdin: JSON.stringify(payload), env: ingestEnv(env), timeoutMs })
    if (out.exitCode !== 0) cli = undefined // the CLI moved or broke: look again next time
  } catch {
    cli = undefined
  }
}

/** Ask for an ingest. At most one per COALESCE_MS; the one that runs carries the latest state. */
function record($: EngineInterface, event: Event) {
  if (!interactive || !snap) return
  pending = event
  if (ingestTimer) return
  void (async () => {
    const wait = delayFor(await nowMs($), lastIngestAt)
    if (ingestTimer) return
    ingestTimer = $.clock.after(wait, () => void flush($).catch(() => undefined))
  })()
}

async function flush($: EngineInterface) {
  ingestTimer = null
  const event = pending
  pending = null
  if (!event || !snap) return
  lastIngestAt = await nowMs($)
  await hydrating
  // The first write waits (briefly) for the first git status, or census_mod.git would be null until the next one.
  if (gitReady) await Promise.race([gitReady, new Promise<void>(done => $.clock.after(3000, done))])
  await refreshEngine($)
  await locateProc($)
  await ingest($, event)
}

// ---- git and gh ----------------------------------------------------------------------------

function scheduleGit($: EngineInterface) {
  if (!interactive || gitTimer) return
  void (async () => {
    const wait = lastGitAt === null ? 0 : Math.max(0, lastGitAt + GIT_COALESCE_MS - (await nowMs($)))
    if (gitTimer) return
    gitTimer = $.clock.after(wait, () => void runGit($).catch(() => undefined))
  })()
}

async function runGit($: EngineInterface) {
  gitTimer = null
  if (!snap) return
  lastGitAt = await nowMs($)
  const cwd = snap.cwd
  const r = await $.process.run(GIT_STATUS_ARGV, { cwd }).catch(() => undefined)
  const first = gitReadyDone
  gitReadyDone = null
  first?.()
  if (!snap || snap.cwd !== cwd) return
  const before = snap.git
  snap.git = r && r.exitCode === 0 ? parseStatus(r.stdout) : null
  if (before?.branch !== snap.git?.branch) {
    snap.pr = null
    // The first sight of a branch is not a change of it.
    if (before !== null) record($, 'branch')
    scheduleGh($, before === null ? 'start' : 'branch')
  }
  repaint($)
}

function scheduleGh($: EngineInterface, why: Why) {
  if (!interactive || !eff.pr) return
  $.clock.after(0, () => void refreshGh($, why).catch(() => undefined))
}

async function refreshGh($: EngineInterface, why: Why) {
  if (!eff.pr) return // answered No: gh is never called
  await hydrating // the worktree path gh runs in is read there
  if (!snap?.git?.branch || snap.git.detached) return
  const key = ghKey(snap.worktreePath ?? snap.cwd, snap.git.branch)
  const branch = snap.git.branch
  const now = await nowMs($)
  const cached = (await $.store.get(key).catch(() => undefined)) as GhEntry | undefined
  if (cached) snap.pr = cached.pr
  if (!shouldRefresh(why, cached, now, lastActiveAt)) return
  const before = snap.pr
  let entry: GhEntry
  try {
    const r = await $.process.run(ghArgv(branch), { cwd: snap.worktreePath ?? snap.cwd, timeoutMs: GH_TIMEOUT_MS })
    const pr = r.exitCode === 0 ? parsePrList(r.stdout) : undefined
    entry = pr === undefined ? { at: cached?.at ?? 0, pr: cached?.pr ?? null, failedAt: now } : { at: now, pr }
  } catch {
    if (!saidNoGh) {
      saidNoGh = true
      $.ui.log('gh unavailable: no PR segment (is gh installed and logged in?)')
    }
    entry = { at: cached?.at ?? 0, pr: cached?.pr ?? null, failedAt: now }
  }
  await $.store.set(key, entry).catch(() => undefined)
  if (!snap || snap.git?.branch !== branch) return
  snap.pr = entry.pr
  if (before?.number !== entry.pr?.number || before?.reviewState !== entry.pr?.reviewState) record($, 'pr')
  repaint($)
}

async function readGitDir($: EngineInterface, cwd: string) {
  return $.process.run(GIT_DIR_ARGV, { cwd }).then(r => ({ exitCode: r.exitCode, stdout: r.stdout })).catch(() => ({ exitCode: 1, stdout: '' }))
}

// ---- lifecycle -----------------------------------------------------------------------------

function cancelTimers() {
  for (const t of [ingestTimer, coldTimer, tickTimer, gitTimer, offerTimer]) t?.cancel()
  ingestTimer = coldTimer = tickTimer = gitTimer = offerTimer = null
}

function armCold($: EngineInterface) {
  coldTimer?.cancel()
  coldTimer = null
  if (!snap) return
  const at = expiresAtMs(snap.counters, snap.ttl)
  if (at === null || snap.counters.cold) return
  void (async () => {
    const wait = at - (await nowMs($))
    if (wait <= 0 || !snap) return
    coldTimer = $.clock.after(wait, () => {
      coldTimer = null
      repaint($)
      record($, 'cache.cold')
    })
  })()
}

function armTimers($: EngineInterface) {
  tickTimer?.cancel()
  // Countdowns only: redraws, never records.
  tickTimer = $.clock.every(TICK_MS, () => {
    repaint($)
    scheduleGh($, 'age')
  })
  armCold($)
}

/** The git dir (worktree) and the session name: shell-outs kept off the start hooks' path. The first write waits for them. */
function hydrate($: EngineInterface, known?: { exitCode: number; stdout: string }) {
  hydrating = new Promise<void>(done => {
    $.clock.after(0, () => {
      void (async () => {
        await loadSetup($)
        if (!snap) return
        const gitDir = known ?? (await readGitDir($, snap.cwd))
        if (snap) snap.worktreePath = worktreeOf(gitDir)
        const scanned = snap ? titleScanned.get(snap) : undefined
        if (snap) titleScanned.set(snap, snap.transcriptPath ?? '')
        await readName($, snap, scanned !== snap?.transcriptPath)
        repaint($)
        offerOnce($)
      })()
        .catch(() => undefined)
        .finally(done)
    })
  })
}

/** An ended record for a session this process is leaving, from its last snapshot; once per session. */
function closeOld($: EngineInterface, old: Snap | null, why: string) {
  if (!old || ended.has(old.sessionId)) return
  ended.add(old.sessionId)
  $.clock.after(0, () => void ingest($, 'session.end', why, INGEST_TIMEOUT_MS, old).catch(() => undefined))
}

/** (Re)bind the live state to a session. Idempotent: a reload or a repeated start finds it bound. */
async function bind($: EngineInterface, id: string, cwd: string, transcript: string | null, event: Event, gitDir?: { exitCode: number; stdout: string }) {
  const same = snap?.sessionId === id
  ended.delete(id) // a resumed id is live again
  if (!same) {
    const old = snap
    snap = fresh(id, cwd)
    limitsKey = ''
    lastGitAt = null // a new session's first git status is not held back by the old one's
    if (old && event !== 'session.start') {
      closeOld($, old, event.replace('session.', ''))
      setupRun = null // an open setup dialog belongs to the session that is gone
    }
    cancelTimers()
    pending = null
    snap.counters = await loadCounters($, id)
    snap.ttl = snap.counters.ttl ?? DEFAULT_TTL
  }
  if (!snap) return
  const root = configRoot(env)
  snap.transcriptPath = transcript ?? snap.transcriptPath ?? (root ? transcriptPathFor(root, snap.cwd, id) : null)
  await refreshEngine($)
  await locateProc($)
  hydrate($, gitDir)
  armTimers($)
  if (!same || !gitReady) gitReady = new Promise<void>(done => { gitReadyDone = done })
  scheduleGit($)
  record($, event)
  void pruneCounters($, id, await nowMs($))
}

async function isInteractive($: EngineInterface): Promise<boolean> {
  if (interactive !== null) return interactive
  return (await $.session.surfaces().catch(() => [])).length > 0
}

// ---- /census-setup -------------------------------------------------------------------------------------
//
// Asks through $.ui.ask, one question at a time: nothing is submitted, nothing reaches the model, and a
// phone can answer. Each answer is saved the moment it is given, so a /clear or a dismissal loses only
// what was not yet asked. The precedence is the environment, then these answers, then the defaults.

async function loadSetup($: EngineInterface) {
  saved = ((await $.store.get(SETUP_KEY).catch(() => undefined)) as Saved | undefined) ?? {}
  det = await detect($)
  applyEffective($)
}

function applyEffective($: EngineInterface) {
  const before = env.CENSUS_MOD_STORE
  eff = effective(saved, rawEnv, det, configRoot(rawEnv))
  env = { ...rawEnv, CENSUS_MOD_STORE: eff.shadowDir ?? undefined, CENSUS_STATUSLINE_SEGMENTS: eff.segments }
  if (before !== env.CENSUS_MOD_STORE) cli = undefined // another store, another pointer
  repaint($)
}

async function saveAnswer($: EngineInterface, patch: Partial<Saved>) {
  saved = { ...saved, ...patch }
  await $.store.set(SETUP_KEY, saved).catch(() => undefined)
  applyEffective($)
}

const settingsPath = (): string | null => {
  const root = configRoot(rawEnv)
  return root ? `${root}/settings.json` : null
}
const realCensusDir = (): string | null => censusDir({ CENSUS_STORE: rawEnv.CENSUS_STORE, CLAUDE_CONFIG_DIR: rawEnv.CLAUDE_CONFIG_DIR, HOME: rawEnv.HOME })

/** Step 1 of setup, no questions: the CLI and its version, this account's status line, any other writer. */
async function detect($: EngineInterface): Promise<Detection> {
  const out: Detection = { ...NO_DETECTION }
  try {
    out.cliPath = await discover($)
    if (out.cliPath) {
      const root = out.cliPath.replace(/\/scripts\/[^/]+$/, '')
      const meta = await $.fs.read(`${root}/.claude-plugin/plugin.json`).catch(() => undefined)
      try {
        const v = typeof meta === 'string' ? (JSON.parse(meta) as { version?: unknown }).version : undefined
        out.version = typeof v === 'string' ? v : null
      } catch {
        out.version = null
      }
    }
    const path = settingsPath()
    const text = path ? await $.fs.read(path).catch(() => undefined) : undefined
    if (typeof text === 'string') {
      const parsed = parseSettings(text)
      if (!parsed.ok) out.settingsInvalid = true
      else {
        const command = statusLineCommand(parsed.data)
        out.statusLineCommand = command
        if (command) {
          out.ingestBlock = commandIsCensus(command)
          for (const file of scriptCandidates(command, rawEnv.HOME, rawEnv.USERPROFILE)) {
            const script = await $.fs.read(file).catch(() => undefined)
            if (typeof script === 'string' && hasIngestBlock(script)) out.ingestBlock = true
          }
        }
      }
    }
    const dir = realCensusDir()
    if (dir) {
      const files = ((await $.fs.list(`${dir}/sessions`).catch(() => [])) as { name: string; mtimeMs: number }[])
        .filter(f => f.name.endsWith('.json'))
        .sort((a, b) => b.mtimeMs - a.mtimeMs)
        .slice(0, 20)
      const entries: { updatedAt: number; hasCensusMod: boolean }[] = []
      for (const f of files) {
        const body = await $.fs.read(`${dir}/sessions/${f.name}`).catch(() => undefined)
        try {
          const d = JSON.parse(typeof body === 'string' ? body : '{}') as { updated_at?: number; payload?: { census_mod?: unknown } }
          if (typeof d.updated_at === 'number') entries.push({ updatedAt: d.updated_at * 1000, hasCensusMod: d.payload?.census_mod !== undefined })
        } catch {
          // a file caught mid-write
        }
      }
      out.otherWriter = writerActive(entries, await nowMs($))
    }
  } catch {
    // detection is advice; setup goes on with what it has
  }
  return out
}

function say($: EngineInterface, headline: string, lines: string[] = []) {
  $.ui.toast(headline)
  for (const l of [headline, ...lines]) $.ui.log(l)
}

const writeSettings = async ($: EngineInterface, path: string, text: string): Promise<boolean> => {
  // Through a symlink to its target (a dotfiles repo), never replacing the link; a temp file beside the
  // target, started as a copy so the mode survives, then renamed over it: a reader never sees half a file.
  const target = (await $.fs.stat(path, { resolve: true }).catch(() => undefined))?.realPath ?? path
  const tmp = settingsTmp(target)
  try {
    await $.process.run(['cp', '-p', target, tmp]).catch(() => undefined)
    await $.fs.write(tmp, text)
    const mv = await $.process.run(['mv', '-f', tmp, target])
    if (mv.exitCode === 0) return true
  } catch {
    // fall through to the cleanup
  }
  await $.process.run(['rm', '-f', tmp]).catch(() => undefined)
  return false
}

/** Remove this account's statusLine for the band to replace; false (and a message) when it was left alone. */
async function removeOwnStatusLine($: EngineInterface): Promise<{ done: boolean; backup?: string }> {
  const path = settingsPath()
  const dir = realCensusDir()
  if (!path || !dir) return { done: false }
  const text = await $.fs.read(path).catch(() => undefined)
  if (typeof text !== 'string') return { done: false }
  const r = removeStatusLine(text, path, new Date(await nowMs($)).toISOString())
  if (!r.ok) {
    if (r.reason === 'invalid') say($, `🧭 census-setup: ${path} is not valid JSON, so I left your status line alone`)
    return { done: r.reason === 'none' }
  }
  const backup = `${dir}/${BACKUP_FILE}`
  const existing = ((await $.fs.read(backup).catch(() => undefined)) as string | undefined) ?? null
  if (backupBlocks(existing, r.backup)) {
    say($, `🧭 census-setup: the backup already holds a different status line (${backup}), so I left your status line alone`)
    return { done: false }
  }
  try {
    await $.fs.write(backup, r.backup) // first: the removal is undoable before it happens
  } catch {
    say($, `🧭 census-setup: could not write the backup ${backup}, so I left your status line alone`)
    return { done: false }
  }
  if (!(await writeSettings($, path, r.text))) {
    say($, `🧭 census-setup: could not write ${path}, so I left your status line alone`)
    return { done: false }
  }
  return { done: true, backup }
}

/** `/census-setup off`: stop recording and drawing, and put a status line we removed back exactly. */
async function turnOff($: EngineInterface) {
  await saveAnswer($, { record: 'no', draw: false, answeredAt: await nowMs($), offered: true })
  const lines: string[] = ['recording: off', 'band: off']
  const path = settingsPath()
  const dir = realCensusDir()
  const backupPath = dir ? `${dir}/${BACKUP_FILE}` : null
  const backup = backupPath ? ((await $.fs.read(backupPath).catch(() => undefined)) as string | undefined) ?? null : null
  if (path && backupPath && backup !== null) {
    const text = await $.fs.read(path).catch(() => undefined)
    const r = restoreStatusLine(typeof text === 'string' ? text : '', backup)
    if (r.done === 'restored') {
      if (await writeSettings($, path, r.text)) {
        await $.process.run(['rm', '-f', backupPath]).catch(() => undefined)
        lines.push(`your status line is back in ${path}`)
      } else lines.push(`could not write ${path}: your status line is still backed up in ${backupPath}`)
    } else if (r.done === 'already') {
      await $.process.run(['rm', '-f', backupPath]).catch(() => undefined)
      lines.push('your status line is already in place')
    } else lines.push(`left ${path} alone (${r.why === 'present' ? 'it has a different status line now' : r.why === 'invalid' ? 'it is not valid JSON' : 'no usable backup'}); the backup stays in ${backupPath}`)
  }
  say($, '🧭 census-mod is off', [...lines, 'run /census-setup to turn it on again'])
}

type Answer = { a: string } | 'dismissed' | 'superseded'

async function askOne($: EngineInterface, run: object, q: { header: string; question: string; options: string[] }): Promise<Answer> {
  const got = await $.ui.ask(q.question, { header: q.header, options: q.options }).then(a => ({ a: String(a) }), () => null)
  if (setupRun !== run) return 'superseded' // a /clear or another setup took over while the dialog was open
  return got ?? 'dismissed'
}

async function setup($: EngineInterface, run: object, mode: 'full' | 'offer') {
  await loadSetup($)
  if (!saved.offered) await saveAnswer($, { offered: true }) // asked, so never offered again, whatever the answer
  const stop = async (why: Answer) => {
    if (why === 'dismissed') say($, '🧭 census-setup stopped; what you answered is saved. Run /census-setup to carry on')
    if (setupRun === run) setupRun = null
  }
  if (mode === 'offer') {
    await saveAnswer($, { offered: true })
    const a = await askOne($, run, Q.offer())
    if (typeof a !== 'object' || !is(a.a, L.offerYes)) {
      if (setupRun === run) setupRun = null // not now, or dismissed: the defaults stand and it is not offered again
      return
    }
  }
  // step 1, no questions
  const d = det
  say($, '🧭 census-setup: looking around', [
    `census CLI: ${d.cliPath ?? 'not found'}${d.version ? ` (${d.version})` : ''}`,
    `status line: ${d.statusLineCommand ?? 'none'}${d.ingestBlock ? ' (it records into census)' : ''}${d.settingsInvalid ? ' (settings.json is not valid JSON)' : ''}`,
    `another writer on the store: ${d.otherWriter ? 'yes, active in the last few minutes' : 'no'}`,
  ])
  let recordMode: 'yes' | 'shadow' | 'no' | null = null
  if (!d.cliPath) {
    say($, '🧭 census-setup: census not found — install the census plugin; nothing can be recorded until then')
    recordMode = 'no'
  } else if (d.version && !atLeast(d.version, MIN_CENSUS)) {
    const a = await askOne($, run, Q.old(d.version))
    if (typeof a !== 'object') return stop(a)
    if (is(a.a, L.oldNo)) {
      recordMode = 'no'
      await saveAnswer($, { record: recordMode })
    }
  }
  let replace = false
  if (recordMode === null) {
    const a = await askOne($, run, Q.record(d))
    if (typeof a !== 'object') return stop(a)
    recordMode = recordFrom(a.a) ?? 'no'
    replace = replaceFrom(a.a)
    await saveAnswer($, { record: recordMode })
  }
  // Replacing the status line means census-mod must draw: only ask where.
  const band = await askOne($, run, replace ? Q.place() : Q.draw())
  if (typeof band !== 'object') return stop(band)
  const placement = placementFrom(band.a)
  const drawOn = placement !== null
  await saveAnswer($, placement ? { draw: true, placement } : { draw: false })
  let removed: string | undefined
  if (recordMode === 'yes' && d.ingestBlock) {
    let choice: ReturnType<typeof writersFrom>
    if (replace && drawOn) choice = 'remove'
    else {
      const a = await askOne($, run, Q.writers(drawOn, d.otherWriter))
      if (typeof a !== 'object') return stop(a)
      choice = writersFrom(a.a)
    }
    if (choice === 'remove') {
      const r = await removeOwnStatusLine($)
      if (r.done) {
        removed = r.backup
        det = await detect($)
      } else {
        recordMode = 'no'
        await saveAnswer($, { record: recordMode })
      }
    } else if (choice === 'keep') {
      recordMode = 'no'
      await saveAnswer($, { record: recordMode })
    }
  }
  if (recordMode === 'no' && !drawOn) {
    await turnOff($)
    if (setupRun === run) setupRun = null
    return
  }
  let preset = saved.preset
  if (drawOn) {
    const a = await askOne($, run, Q.preset())
    if (typeof a !== 'object') return stop(a)
    preset = presetFrom(a.a) ?? 'two'
    await saveAnswer($, { preset })
  }
  const pr = await askOne($, run, Q.pr())
  if (typeof pr !== 'object') return stop(pr)
  await saveAnswer($, { pr: is(pr.a, L.prYes), answeredAt: await nowMs($), offered: true })
  if (setupRun !== run) return
  setupRun = null
  const hasVitals = d.cliPath ? await $.fs.exists(d.cliPath.replace(/[^/\\]*$/, 'vitals.py')).catch(() => false) : false
  say($, '🧭 census-mod is set up', [
    `recording: ${recordMode === 'yes' ? 'the real census store' : recordMode === 'shadow' ? `shadow store ${eff.shadowDir ?? ''}` : 'off'}`,
    `band: ${drawOn ? `on, ${eff.placement === 'below' ? 'below the input' : 'above the input'}, ${PRESETS[preset ?? 'two']}` : 'off'}${rawEnv.CENSUS_STATUSLINE_SEGMENTS?.trim() ? ' (CENSUS_STATUSLINE_SEGMENTS overrides the layout)' : ''}`,
    `PR segment (gh): ${saved.pr === false ? 'off, gh is never called' : 'on'}`,
    ...(removed ? [`your status line was removed from settings.json; it is backed up in ${removed}`] : []),
    'undo any time: /census-setup off (it restores a removed status line exactly), or /census-setup to answer again',
    ...(hasVitals ? ['📊 /census:vitals shows this session on your phone'] : []),
  ])
}

function startSetup($: EngineInterface, mode: 'full' | 'offer') {
  const run = {}
  setupRun = run
  // After the command has replied: the dialogs follow it rather than holding it open.
  $.clock.after(0, () => void setup($, run, mode).catch(() => { if (setupRun === run) setupRun = null }))
}

/** The first session after install: say so once, ever. An answer or a dismissal both count. */
function offerOnce($: EngineInterface) {
  if (saved.offered || setupRun || !interactive || offerTimer) return
  const id = snap?.sessionId
  offerTimer = $.clock.after(3000, () => {
    offerTimer = null
    // A quick exit (or a /clear) in between: there is no session left to ask in.
    if (saved.offered || setupRun || !id || snap?.sessionId !== id) return
    startSetup($, 'offer')
  })
}

const DEFAULT_COLUMNS = 100

/** The status line as runs, from the live snapshot: the same lines whichever site draws them. */
async function statusLines($: EngineInterface): Promise<Line[]> {
  if (!snap) return []
  const now = (await nowMs($)) / 1000
  const c = snap.counters
  const expires = expiresAtMs(c, snap.ttl)
  const input: RenderInput = {
    now,
    ctxPct: snap.ctxPct,
    cache: { hitRatio: c.lastRatio, requests: c.requests, warm: isWarm(c, snap.ttl, now * 1000), expiresAt: expires === null ? null : expires / 1000, misses: 0 },
    limits: rateLimitsOf(snap.rateLimits),
    costUsd: snap.costUsd,
    durationMs: snap.startedAt === null ? null : now * 1000 - snap.startedAt,
    modelName: snap.model?.display_name ?? null,
    git: snap.git,
    pr: snap.pr,
    cwd: snap.worktreePath ?? snap.cwd,
    env,
  }
  return draw(input)
}

/** One <Box> row per line, a <Text> per coloured run. */
function statusRows($: EngineInterface, e: Parameters<typeof $.ui.resolve>[0], lines: Line[]) {
  const { Box, Text } = $.ui.resolve(e)
  return lines.map((line, i) => (
    <Box key={`census-${i}`}>
      {line.map((run, j) => (
        <Text key={`r${j}`} color={run.tone ? TONE_COLOR[run.tone] : undefined} bold={run.bold} wrap="truncate-end">
          {run.t}
        </Text>
      ))}
    </Box>
  ))
}

/** Our work after `next`: whatever it throws must not cost the other mods their result. */
async function quietly(work: () => Promise<void>): Promise<void> {
  try {
    await work()
  } catch {
    // recording is best-effort; the session carries on
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const r = await next(e)
    interactive = e.isInteractive
    if (!interactive) return r
    await quietly(async () => {
      await $.command.register({ name: 'census-setup', description: 'Guided census-mod setup: record, draw, layout, gh. `off` stops it.', argumentHint: '[off]' }).catch(() => undefined)
      rawEnv = await loadEnv($)
      env = { ...rawEnv }
      await bind($, await $.session.id(), e.cwd, null, 'session.start')
    })
    return r
  })

  // Every source: startup, resume, clear (a new session id), compact, fork.
  on('classic.SessionStart', async ($, e, next) => {
    const r = await next(e)
    let watch: string[] = []
    await quietly(async () => {
      if (!(await isInteractive($))) return
      interactive = true
      if (Object.keys(rawEnv).length === 0) {
        rawEnv = await loadEnv($)
        env = { ...rawEnv }
      }
      // watchPaths are this hook's answer, so this one git call is awaited; bind reuses it.
      const gitDir = await readGitDir($, e.cwd)
      watch = watchPaths(gitDir)
      if (e.source !== 'compact') {
        const event: Event = e.source === 'startup' ? 'session.start' : (`session.${e.source}` as Event)
        await bind($, e.session_id, e.cwd, e.transcript_path || null, event, gitDir)
      } else if (snap && e.transcript_path) snap.transcriptPath = e.transcript_path
    })
    return watch.length ? { ...r, watchPaths: [...(r.watchPaths ?? []), ...watch] } : r
  })

  on('turn.complete', async ($, e, next) => {
    const r = await next(e)
    if (!interactive || !snap || e.agentId !== undefined || !e.usage) return r
    const usage = e.usage
    await quietly(async () => {
      if (!snap) return
      const now = await nowMs($)
      lastActiveAt = now
      snap.counters = addTurn(snap.counters, usage, now)
      await saveCounters($)
      // The reads below shell out: off the turn's path. They belong to THIS session's snapshot: a /clear
      // that rebinds meanwhile must not get this transcript's ttl or title, nor a turn.complete write.
      const mine = snap
      $.clock.after(0, () => {
        void (async () => {
          await readTtl($, mine)
          await readName($, mine)
          await saveCounters($, mine)
          if (snap !== mine) return
          armCold($)
          repaint($)
          record($, 'turn.complete')
        })().catch(() => undefined)
      })
    })
    return r
  })

  on('session.measure', async ($, e, next) => {
    const r = await next(e)
    if (!interactive || !snap) return r
    await quietly(async () => {
      if (!snap) return
      snap.ctxPct = e.context.percent ?? null
      snap.ctxWindow = e.context.window ?? snap.ctxWindow
      snap.costUsd = e.cost?.usd ?? snap.costUsd
      const rates = e.rateLimits as RateLimit[]
      const key = limitsFingerprint(rates)
      if (key !== limitsKey) {
        limitsKey = key
        snap.rateLimits = rates
        record($, 'rate-limit')
      }
      repaint($)
    })
    return r
  })

  on('classic.PostModelSwitch', async ($, e, next) => {
    const r = await next(e)
    if (!interactive || !snap) return r
    await quietly(async () => {
      if (!snap) return
      if (e.to_model) snap.model = modelOf(e.to_model)
      const label = (e as unknown as { cache_ttl?: unknown }).cache_ttl
      if (label === '1h' || label === '5m') {
        snap.ttl = label
        snap.counters = withTtl(snap.counters, label)
        armCold($)
      }
      repaint($)
      record($, 'model')
    })
    return r
  })

  on('classic.CwdChanged', async ($, e, next) => {
    const r = await next(e)
    if (!interactive || !snap) return r
    await quietly(async () => {
      if (!snap) return
      snap.cwd = e.new_cwd
      snap.worktreePath = worktreeOf(await readGitDir($, e.new_cwd))
      lastGitAt = null
      scheduleGit($)
      repaint($)
      record($, 'cwd')
    })
    return r
  })

  // A compaction rewrites the prefix: the next request writes the cache afresh.
  on('classic.PostCompact', async ($, e, next) => {
    const r = await next(e)
    if (!interactive || !snap) return r
    await quietly(async () => {
      if (!snap) return
      snap.counters = compacted(snap.counters, await nowMs($))
      await saveCounters($)
      coldTimer?.cancel()
      coldTimer = null
      repaint($)
      record($, 'compact')
    })
    return r
  })

  on('classic.FileChanged', async ($, e, next) => {
    scheduleGit($)
    return next(e)
  })

  // After the tool ran: its effect is what can have moved git or the PR.
  on('tool.call', async ($, e, next) => {
    const r = await next(e)
    if (!interactive || !snap) return r
    await quietly(async () => {
      const call = e as unknown as { tool: string; command?: unknown }
      lastActiveAt = await nowMs($)
      if (touchesGit(call.tool)) scheduleGit($)
      if (call.tool === 'Bash' && typeof call.command === 'string' && touchesPr(call.command)) scheduleGh($, 'push')
    })
    return r
  })

  // The ending session's last word: runs under the chain's shared budget, so it carries its own timeout.
  on('command.run', { command: 'census-setup' }, async ($, e) => {
    const args = ((e as unknown as { args?: string }).args ?? '').trim()
    if (args === 'off') {
      setupRun = null
      await quietly(async () => { if (Object.keys(rawEnv).length === 0) { rawEnv = await loadEnv($); env = { ...rawEnv } } await loadSetup($); await turnOff($) })
      return { text: 'census-mod is off. /census-setup to turn it on again.' }
    }
    if (args !== '') return { text: 'Usage: /census-setup (guided setup) or /census-setup off' }
    if (Object.keys(rawEnv).length === 0) { rawEnv = await loadEnv($); env = { ...rawEnv } }
    startSetup($, 'full')
    return { text: '🧭 census-setup: a few questions follow.' }
  })

  on('session.end', async ($, e, next) => {
    await quietly(async () => {
      if (interactive && snap && snap.sessionId === e.sessionId) {
        cancelTimers()
        pending = null
        const timeoutMs = endTimeoutMs(next.budget.remainingMs)
        if (timeoutMs !== null && !ended.has(e.sessionId)) {
          ended.add(e.sessionId)
          await ingest($, 'session.end', e.reason, timeoutMs)
        }
      }
    })
    return next(e)
  })

  // Above the input: the band. Ours first, whatever other mods draw beneath it after.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const inner = await next(e)
    if (e.props.hasSurvey || !interactive || !snap || !eff.draw || eff.placement !== 'above') return inner
    const lines = (await statusLines($)).slice(0, Math.max(0, e.props.maxRows)).map(l => fit(l, e.props.bodyColumns))
    if (lines.length === 0) return inner
    const { Box } = $.ui.resolve(e)
    return (
      <Box flexDirection="column">
        {statusRows($, e, lines)}
        {inner}
      </Box>
    )
  })

  // Below the input: under Claude Code's own hint line. The engine always draws its permission pill and hint
  // first and a tree cannot go above them, so the engine's line (`inner`) leads and our rows follow on their own
  // lines; a tree without `inner` would put row one on the pill's line. Drawn while typing and while working too.
  on('ui.render', { component: 'PromptHint' }, async ($, e, next) => {
    const inner = await next(e)
    if (!interactive || !snap || !eff.draw || eff.placement !== 'below') return inner
    const columns = e.viewport?.columns ?? DEFAULT_COLUMNS
    const lines = (await statusLines($)).map(l => fit(l, columns))
    if (lines.length === 0) return inner
    const { Box } = $.ui.resolve(e)
    return (
      <Box flexDirection="column">
        {inner}
        {statusRows($, e, lines)}
      </Box>
    )
  })
}
