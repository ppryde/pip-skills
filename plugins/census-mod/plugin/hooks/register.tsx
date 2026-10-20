import type { EngineInterface, Register, Timer } from 'claude-code'
import { COUNTER_KEEP_MS, EMPTY_COUNTERS, STORE_PREFIX, TAIL_CMD, addTurn, compacted, counterKey, DEFAULT_TTL, expiresAtMs, isWarm, parseWrites, ttlFromWrites, ttlMs, withTtl } from '../core/cache'
import { INGEST_TIMEOUT_MS, bundledCli, censusDir, delayFor, endTimeoutMs, ingestArgv, ingestEnv } from '../core/census'
import type { CensusEnv } from '../core/census'
import { GH_TIMEOUT_MS, ghArgv, ghKey, parsePrList, shouldRefresh, touchesPr } from '../core/gh'
import type { GhEntry, Why } from '../core/gh'
import { COALESCE_MS as GIT_COALESCE_MS, GIT_DIR_ARGV, GIT_STATUS_ARGV, parseStatus, touchesGit, watchPaths, worktreeOf } from '../core/git'
import { homeOf, joinPath } from '../core/home'
import { HINT_CONFIRM_MS, applyPatch, gitOperationOf, hasDraftFlag, hintPrNumber, markStale, patchFor, payloadPrOf, prKey, prPrefix, repoOf, toPr } from '../core/prstate'
import type { PrRecord } from '../core/prstate'
import { configRoot, transcriptPathFor } from '../core/name'
import { PYTHON_CANDIDATES, cacheLinesFromText, copyModeArgv, moveArgv, pickPython, removeArgv, titleLinesFromText } from '../core/portable'
import { buildPayload, modelOf, rateLimitsOf } from '../core/payload'
import type { Event } from '../core/payload'
import { TITLE_ARGV, TITLE_TAIL_CMD, findProc, lastTitle } from '../core/registry'
import { TONE_COLOR, draw, fit } from '../core/render'
import { subagentDir, subagentShown, sumSubagents } from '../core/subagents'
import type { SubagentCache } from '../core/subagents'
import { BACKUP_FILE, backupBlocks, budgetFrom, hasCostBar, CLEAN_PRESETS, isShowMe, styleFrom, placementFrom, replaceFrom, L, NO_DETECTION, PRESETS, Q, SETUP_KEY, commandIsCensus, continueAnyway, enabledCensusPlugins, effective, hasIngestBlock, parseSettings, presetFrom, recordFrom, removeStatusLine, restoreStatusLine, scriptCandidates, settingsTmp, statusLineCommand, writerActive, writersFrom, is } from '../core/setup'
import type { Detection, Effective, Saved, Style } from '../core/setup'
import type { Line, RenderEnv, RenderInput } from '../core/render'
import type { Counters, RateLimit, Snap } from '../core/types'

// The effectful shell: the ONLY file that touches `$`. Decisions live in ../core.
//
// State is module variables plus $.store (counters, gh cache): a hot reload loses the variables, and
// session.start (which re-fires on a reload) rebuilds them. Nothing is kept in $.state, so a /clear
// has nothing to wipe and classic.SessionStart(clear) simply binds the new session.

type Env = CensusEnv & RenderEnv & { USERPROFILE?: string; CENSUS_MOD_PLACEMENT?: string; CENSUS_MOD_PR_HINT?: string }

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
let cli: string | null | undefined // census-mod's own bundled recorder, once found there
let saidNoCli = false
let python: string[] | null | undefined // the launcher that passed the Python 3.9+ probe, once; null = none found
let shell: boolean | undefined // whether `sh` runs here (it does not on Windows)
let saidNoGh = false
const repoByDir = new Map<string, string | null>() // working dir -> owner/name of origin (null = none), asked once per dir

const TICK_MS = 30_000
const SUBAGENT_MIN_MS = 5_000 // a session.measure storm reads the subagent transcripts at most this often
const subCache: SubagentCache = new Map() // subagent transcript path -> its size and cost when last read
let subAt: number | null = null
let subRunning = false

async function nowMs($: EngineInterface): Promise<number> {
  return $.clock.now()
}

async function loadEnv($: EngineInterface): Promise<Env> {
  return {
    CENSUS_MOD_STORE: await $.env.get('CENSUS_MOD_STORE'),
    CENSUS_STORE: await $.env.get('CENSUS_STORE'),
    CLAUDE_CONFIG_DIR: await $.env.get('CLAUDE_CONFIG_DIR'),
    HOME: await $.env.get('HOME'),
    USERPROFILE: await $.env.get('USERPROFILE'),
    HOMEDRIVE: await $.env.get('HOMEDRIVE'),
    HOMEPATH: await $.env.get('HOMEPATH'),
    CENSUS_STATUSLINE_SEGMENTS: await $.env.get('CENSUS_STATUSLINE_SEGMENTS'),
    CENSUS_MOD_PLACEMENT: await $.env.get('CENSUS_MOD_PLACEMENT'),
    CENSUS_MOD_PR_HINT: await $.env.get('CENSUS_MOD_PR_HINT'),
    CENSUS_STATUSLINE_MASCOT: await $.env.get('CENSUS_STATUSLINE_MASCOT'),
    CLAUDE_COST_BUDGET: await $.env.get('CLAUDE_COST_BUDGET'),
    CLAUDE_PROFILE: await $.env.get('CLAUDE_PROFILE'),
  }
}

function fresh(id: string, cwd: string): Snap {
  return {
    sessionId: id, transcriptPath: null, cwd, worktreePath: null, version: null, model: null, sessionName: null,
    ctxPct: null, ctxWindow: null, costUsd: null, subagentUsd: null, startedAt: null, rateLimits: [],
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
  await refreshSubagents($, true)
}

/**
 * The subagents' cost from their transcripts: only files that grew are re-read. Throttled unless `force`
 * (a turn's write); applied to the snapshot it was asked for. Repaints when the figure moved.
 */
async function refreshSubagents($: EngineInterface, force = false) {
  const s = snap
  const dir = subagentDir(s?.transcriptPath ?? null)
  if (!s || !dir || subRunning) return
  const now = await nowMs($)
  if (!force && subAt !== null && now - subAt < SUBAGENT_MIN_MS) return
  subAt = now
  subRunning = true
  try {
    const entries = await $.fs.list(dir).catch(() => [])
    const read = (path: string) => Promise.resolve($.fs.read(path)).then(t => (typeof t === 'string' ? t : null), () => null)
    const usd = await sumSubagents(dir, entries, subCache, read)
    if (usd !== s.subagentUsd) {
      s.subagentUsd = usd
      if (s === snap) repaint($)
    }
  } catch {
    // the 🕵️ figure is a nicety: keep the last one
  } finally {
    subRunning = false
  }
}

const limitsFingerprint = (l: RateLimit[]): string => l.map(x => `${x.kind}:${x.percentUsed}:${x.resetsAt ?? ''}`).sort().join('|')

async function locateProc($: EngineInterface) {
  if (!snap || snap.proc) return // looked for again on every write until found: it is one small read
  try {
    const root = configRoot(env)
    if (!root) return
    const sessions = joinPath(root, 'sessions')
    const entries = await $.fs.list(sessions)
    const files: { text: string }[] = []
    for (const f of entries) {
      if (!f.name.endsWith('.json')) continue
      const text = await $.fs.read(joinPath(sessions, f.name)).catch(() => undefined)
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
    if (!(await hasShell($))) {
      s.sessionName = lastTitle(titleLinesFromText(await transcriptText($, s.transcriptPath), whole ? undefined : 262144)) ?? s.sessionName
      return
    }
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
    const out = (await hasShell($))
      ? await $.process.run(['sh', '-c', TAIL_CMD, 'sh', s.transcriptPath]).then(r => (r.exitCode === 0 ? r.stdout : ''))
      : cacheLinesFromText(await transcriptText($, s.transcriptPath))
    const found = out ? ttlFromWrites(parseWrites(out)) : null
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

/** census-mod records through its own bundled copy of census's ingest: no census plugin is ever needed or looked for. */
async function discover($: EngineInterface): Promise<string | null> {
  if (cli) return cli
  let root: string | undefined
  try {
    root = $.plugin.root
  } catch {
    root = undefined
  }
  const path = root ? bundledCli(root) : null
  if (path && (await $.fs.exists(path).catch(() => false))) return (cli = path)
  if (!saidNoCli) {
    saidNoCli = true
    $.ui.log('census-mod\'s bundled recorder is missing (scripts/cli.py): reinstall census-mod. The band is drawn, nothing is recorded')
  }
  return null
}

/** `python3`, `python` or `py -3`, the first that passes the Python 3.9+ probe; asked once per process. null: none, said once in the log. */
async function pythonLauncher($: EngineInterface, budgetMs = INGEST_TIMEOUT_MS): Promise<string[] | null> {
  if (python !== undefined) return python
  // Three probes share the hook's budget (a session.end has little): too little left, and the probe waits for a later ingest.
  const probeMs = Math.min(2000, Math.floor(budgetMs / 6))
  if (probeMs < 200) return null
  const found = await pickPython(async argv => (await $.process.run(argv, { timeoutMs: probeMs })).exitCode === 0)
  python = found
  if (!python) $.ui.log('census-mod found no Python (tried python3, python, py -3): the band is drawn, nothing is recorded')
  return python
}

/** Whether `sh` runs here; asked once per process. */
async function hasShell($: EngineInterface): Promise<boolean> {
  if (shell === undefined) shell = await $.process.run(['sh', '-c', 'exit 0'], { timeoutMs: 5000 }).then(r => r.exitCode === 0, () => false)
  return shell
}

/** The transcript's text (a file over the engine's read cap reads as nothing): for where there is no sh/tail/grep. */
let lastRead: { path: string; at: number; text: Promise<string> } | undefined
const transcriptText = async ($: EngineInterface, path: string): Promise<string> => {
  // The TTL and the title are read together every turn: one read serves both.
  const now = await nowMs($)
  if (lastRead && lastRead.path === path && now - lastRead.at < 2000) return lastRead.text
  const text = Promise.resolve($.fs.read(path)).then(t => (typeof t === 'string' ? t : ''), () => '')
  lastRead = { path, at: now, text }

  return text
}

async function ingest($: EngineInterface, event: Event, endedReason?: string, timeoutMs = INGEST_TIMEOUT_MS, of: Snap | null = snap) {
  if (!of) return
  if (eff.record === 'no') return
  const path = await discover($)
  if (!path) return
  const py = await pythonLauncher($, timeoutMs)
  const payload = buildPayload(of, await nowMs($), event, endedReason)
  const run = (launcher: readonly string[]) => $.process.run(ingestArgv(path, launcher), { stdin: JSON.stringify(payload), env: ingestEnv(env), timeoutMs })
  try {
    if (!py) {
      // Not chosen yet and too little budget to probe (a session.end has about a second, and no later ingest): run the
      // ingest itself through each launcher in turn. One that cannot be spawned (or is missing: 127, 9009) is skipped.
      if (python !== undefined) return
      for (const candidate of PYTHON_CANDIDATES) {
        const out = await run(candidate).catch(() => undefined)
        if (!out || out.exitCode === 127 || out.exitCode === 9009) continue
        python = [...candidate]
        if (out.exitCode !== 0) cli = undefined
        return
      }
      return
    }
    const out = await run(py)
    if (out.exitCode !== 0) cli = undefined // the bundle moved or broke: look again next time
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
    snap.pr = await prFromEvents($) // a PR the mod saw on this branch (any session) draws at once; else none until gh says
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

/** What a lookup came to: `answered` = gh spoke (a PR or none), `failed` = it did not and nothing changed, `skipped` = not asked. */
type GhOutcome = 'answered' | 'failed' | 'skipped' | 'no-branch'

/** `manual` (/census-mod:pr-refresh) asks once whatever the PR answer is; every other trigger needs it Yes. */
async function refreshGh($: EngineInterface, why: Why): Promise<GhOutcome> {
  if (!eff.pr && why !== 'manual') return 'skipped' // the PR answer is No (the default): gh is never called on its own
  await hydrating // the worktree path gh runs in is read there
  if (!snap?.git?.branch || snap.git.detached) return 'no-branch'
  const key = ghKey(snap.worktreePath ?? snap.cwd, snap.git.branch)
  const branch = snap.git.branch
  const now = await nowMs($)
  const cached = (await $.store.get(key).catch(() => undefined)) as GhEntry | undefined
  if (cached) {
    const recorded = await recordedPr($)
    snap.pr = recorded === undefined ? cached.pr : recorded
  } // a record that says "not open" (null) beats the gh cache; no record (undefined) falls back to it
  if (!shouldRefresh(why, cached, now, lastActiveAt)) return 'skipped'
  const before = snap.pr
  let entry: GhEntry
  let answered = false
  try {
    const r = await $.process.run(ghArgv(branch), { cwd: snap.worktreePath ?? snap.cwd, timeoutMs: GH_TIMEOUT_MS })
    const pr = r.exitCode === 0 ? parsePrList(r.stdout) : undefined
    entry = pr === undefined ? { at: cached?.at ?? 0, pr: cached?.pr ?? null, failedAt: now } : { at: now, pr }
    answered = pr !== undefined
  } catch {
    if (!saidNoGh) {
      saidNoGh = true
      $.ui.log('gh unavailable: no PR segment (is gh installed and logged in?)')
    }
    entry = { at: cached?.at ?? 0, pr: cached?.pr ?? null, failedAt: now }
  }
  await $.store.set(key, entry).catch(() => undefined)
  if (!snap || snap.git?.branch !== branch) return answered ? 'answered' : 'failed'
  // Only an answer is a word about the PR: a failed or backed-off gh must not reopen or refresh a record.
  if (answered) await recordGhAnswer($, branch, entry, now)
  // One precedence decides every draw (events > status-line pr > gh), as on the tick; no record falls back to the cache.
  const recorded = await recordedPr($)
  if (!snap) return answered ? 'answered' : 'failed'
  snap.pr = recorded === undefined ? entry.pr : recorded
  if (before?.number !== snap.pr?.number || before?.reviewState !== snap.pr?.reviewState) record($, 'pr')
  repaint($)

  return answered ? 'answered' : 'failed'
}

// ---- PR state from tool events (WF-269) ---------------------------------------------------------
// The engine reports `gitOperation` on a Bash result: a created, readied, closed or merged PR and a push. That is
// kept per repo+branch in $.store (shared by every session of the account), so the PR segment needs no gh call and
// works with the PR setting off. gh, where it is on, only adds the review state and what happened outside the session.

/** `owner/name` of the origin of the directory the session works in; null when there is none. Asked once per directory. */
async function repoName($: EngineInterface): Promise<string | null> {
  if (!snap) return null
  const dir = snap.worktreePath ?? snap.cwd
  if (repoByDir.has(dir)) return repoByDir.get(dir) ?? null
  const r = await $.process.run(['git', 'remote', 'get-url', 'origin'], { cwd: dir, timeoutMs: 5000 }).catch(() => undefined)
  const repo = r && r.exitCode === 0 ? repoOf(r.stdout) : null
  repoByDir.set(dir, repo)

  return repo
}

const currentBranch = (): string | null => (snap?.git?.branch && !snap.git.detached ? snap.git.branch : null)

async function readRecord($: EngineInterface, key: string): Promise<PrRecord | undefined> {
  const got = (await $.store.get(key).catch(() => undefined)) as PrRecord | undefined

  return got && typeof got === 'object' && typeof got.number === 'number' ? got : undefined
}

/** The drawn PR of the current branch from its record; null when the record says none; undefined when there is no record. */
async function recordedPr($: EngineInterface): Promise<Snap['pr'] | undefined> {
  const branch = currentBranch()
  if (!branch) return undefined
  const repo = await repoName($)
  const rec = repo ? await readRecord($, prKey(repo, branch)) : undefined
  const now = await nowMs($)
  // The session's own events outrank the status-line payload's pr, which outranks gh.
  if (rec?.source === 'event') return toPr(rec, now)
  const line = await payloadPr($, branch, now)
  if (line) return line

  return rec ? toPr(rec, now) : undefined
}

/** The pr a status-line COMMAND wrote into this session's census record (census's ingest keeps it as `status_line_pr`). */
async function payloadPr($: EngineInterface, branch: string, now: number): Promise<Snap['pr']> {
  const sid = snap?.sessionId
  const dir = censusDir(rawEnv)
  if (!sid || !dir || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(sid)) return null
  const text = await $.fs.read(joinPath(dir, 'sessions', `${sid}.json`)).catch(() => undefined)

  return typeof text === 'string' ? payloadPrOf(text, now, branch) : null
}

/** The drawn PR of the current branch from its record; null when the record says none (or there is none). */
async function prFromEvents($: EngineInterface): Promise<Snap['pr']> {
  return (await recordedPr($)) ?? null
}

/** Every record of the repo, so a PR can be found by number whatever branch the command ran on. */
async function recordsOf($: EngineInterface, repo: string): Promise<{ key: string; rec: PrRecord }[]> {
  const keys = ((await $.store.keys().catch(() => [])) as string[]).filter(k => k.startsWith(prPrefix(repo)))
  const out: { key: string; rec: PrRecord }[] = []
  for (const key of keys) {
    const rec = await readRecord($, key)
    if (rec) out.push({ key, rec })
  }

  return out
}

/** Re-derive the snapshot's PR after a record moved, and record the change. */
async function pushPrToSnap($: EngineInterface, always = true) {
  if (!snap) return
  const before = snap.pr
  const after = await prFromEvents($)
  if (!snap) return
  snap.pr = after
  const changed = before?.number !== after?.number || before?.reviewState !== after?.reviewState || before?.stale !== after?.stale
  if (changed) record($, 'pr')
  if (always || changed) repaint($)
}

/** One Bash result's `gitOperation`: a PR action updates (or, when created, starts) the record; a push marks it stale. */
async function applyGitOperation($: EngineInterface, result: unknown, command: string) {
  const op = gitOperationOf(result)
  if (!op || !snap) return
  const repo = await repoName($)
  if (!repo || !snap) return
  const now = await nowMs($)
  const ctx = { sessionId: snap.sessionId, worktree: snap.worktreePath ?? snap.cwd }
  if (op.pr) {
    const all = await recordsOf($, repo)
    const byNumber = all.filter(r => r.rec.number === op.pr!.number).sort((a, b) => b.rec.at - a.rec.at)[0]
    const branch = currentBranch()
    // By number first; the current branch only for a creation (`gh pr close N` can run from any branch).
    const key = byNumber?.key ?? (op.pr.action === 'created' && branch ? prKey(repo, branch) : null)
    if (key) {
      const next = applyPatch(byNumber?.rec, patchFor(op.pr, hasDraftFlag(command)), now, ctx)
      if (next) await $.store.set(key, next).catch(() => undefined)
    }
  }
  if (op.push) {
    const key = prKey(repo, op.push.branch)
    const old = await readRecord($, key)
    if (old) await $.store.set(key, markStale(old)).catch(() => undefined)
  }
  await pushPrToSnap($)
}

/** gh's answer for the branch, as the newest word in its record. An empty answer closes an event record only once it has had time to be listed. */
async function recordGhAnswer($: EngineInterface, branch: string, entry: GhEntry, now: number): Promise<void> {
  const repo = await repoName($)
  if (!repo) return
  const key = prKey(repo, branch)
  const old = await readRecord($, key)
  const ctx = { sessionId: snap?.sessionId ?? '', worktree: snap?.worktreePath ?? snap?.cwd ?? '', source: 'gh' as const }
  let next: PrRecord | undefined = old
  if (entry.pr) {
    next = applyPatch(old, { number: entry.pr.number, ...(entry.pr.url ? { url: entry.pr.url } : {}), state: 'open', ...(entry.pr.reviewState ? { review: entry.pr.reviewState } : old?.review === 'draft' || old?.review === 'pending' ? { review: null } : {}), lastAction: 'gh' }, now, ctx)
  } else if (old && old.state === 'open' && !(old.source === 'event' && now - old.at < GH_LISTING_GRACE_MS)) {
    next = applyPatch(old, { number: old.number, state: 'closed', lastAction: 'gh' }, now, ctx)
  }
  if (next && next !== old) await $.store.set(key, next).catch(() => undefined)
}

const GH_LISTING_GRACE_MS = 2 * 60_000

async function readGitDir($: EngineInterface, cwd: string) {
  return $.process.run(GIT_DIR_ARGV, { cwd }).then(r => ({ exitCode: r.exitCode, stdout: r.stdout })).catch(() => ({ exitCode: 1, stdout: '' }))
}

/**
 * Opt-in (CENSUS_MOD_PR_HINT): the engine's prompt hint names the branch's open PR as `PR #N`. That is the engine's own
 * word, so it confirms an OPEN record of that number (clears "unconfirmed", keeps the record's own source) and nothing
 * else: it never closes or reopens one (the hint lags a close by seconds), and never starts one (it carries no url).
 */
let hintConfirmedAt = 0
async function confirmFromHint($: EngineInterface, hint: unknown) {
  const number = hintPrNumber(hint)
  const branch = currentBranch()
  if (number === null || !branch || !snap) return
  const now = await nowMs($)
  if (now - hintConfirmedAt < HINT_CONFIRM_MS) return
  const repo = await repoName($)
  if (!repo || !snap) return
  const key = prKey(repo, branch)
  const old = await readRecord($, key)
  if (!old || old.number !== number || old.state !== 'open') return
  hintConfirmedAt = now
  if (!old.stale && now - old.at < HINT_CONFIRM_MS) return
  const ctx = { sessionId: snap.sessionId, worktree: snap.worktreePath ?? snap.cwd, source: old.source }
  const next = applyPatch(old, { number, state: 'open', lastAction: 'hint' }, now, ctx)
  if (next) await $.store.set(key, next).catch(() => undefined)
  await pushPrToSnap($)
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
    void refreshSubagents($).catch(() => undefined)
    scheduleGh($, 'age')
    void pushPrToSnap($, false).catch(() => undefined) // a status-line command may have written a pr since
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
    subCache.clear()
    subAt = null
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
  env = { ...rawEnv, CENSUS_MOD_STORE: eff.shadowDir ?? undefined, CENSUS_STATUSLINE_SEGMENTS: eff.segments, CLAUDE_COST_BUDGET: String(eff.budget) }
  repaint($)
}

async function saveAnswer($: EngineInterface, patch: Partial<Saved>) {
  saved = { ...saved, ...patch }
  await $.store.set(SETUP_KEY, saved).catch(() => undefined)
  applyEffective($)
}

const settingsPath = (): string | null => {
  const root = configRoot(rawEnv)
  return root ? joinPath(root, 'settings.json') : null
}
const realCensusDir = (): string | null => censusDir(rawEnv)

/** Step 1 of setup, no questions: this account's status line, any other writer, whether the census plugin is enabled. */
async function detect($: EngineInterface): Promise<Detection> {
  const out: Detection = { ...NO_DETECTION }
  try {
    const path = settingsPath()
    const text = path ? await $.fs.read(path).catch(() => undefined) : undefined
    if (typeof text === 'string') {
      const parsed = parseSettings(text)
      if (!parsed.ok) out.settingsInvalid = true
      else {
        out.censusPlugins = enabledCensusPlugins(parsed.data)
        const command = statusLineCommand(parsed.data)
        out.statusLineCommand = command
        if (command) {
          out.ingestBlock = commandIsCensus(command)
          for (const file of scriptCandidates(command, homeOf(rawEnv) ?? undefined, rawEnv.USERPROFILE)) {
            const script = await $.fs.read(file).catch(() => undefined)
            if (typeof script === 'string' && hasIngestBlock(script)) out.ingestBlock = true
          }
        }
      }
    }
    const dir = realCensusDir()
    if (dir) {
      const files = ((await $.fs.list(joinPath(dir, 'sessions')).catch(() => [])) as { name: string; mtimeMs: number }[])
        .filter(f => f.name.endsWith('.json'))
        .sort((a, b) => b.mtimeMs - a.mtimeMs)
        .slice(0, 20)
      const entries: { updatedAt: number; hasCensusMod: boolean }[] = []
      for (const f of files) {
        const body = await $.fs.read(joinPath(dir, 'sessions', f.name)).catch(() => undefined)
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

/** Remove a file. Windows has no argv-only delete, so there it is emptied, and an empty backup reads as none. */
const removeFile = async ($: EngineInterface, path: string): Promise<void> => {
  const argv = removeArgv(path)
  if (argv) await $.process.run(argv).catch(() => undefined)
  else await $.fs.write(path, '').catch(() => undefined)
}

/** The backup's text; an emptied one (Windows) is no backup. */
const readBackup = async ($: EngineInterface, path: string): Promise<string | null> => {
  const text = (await $.fs.read(path).catch(() => undefined)) as string | undefined

  return typeof text === 'string' && text.trim() ? text : null
}

/**
 * Write `text` over `path`, which `expected` is the text it was derived from. Nothing is written when the file no
 * longer holds `expected` (Claude Code or another session changed it since we read it): their edit is never lost.
 * POSIX: a unique temp file beside the target (started as a copy so the mode survives), re-checked, then renamed
 * over it, so a reader never sees half a file. Windows has no rename to call (cmd would parse the path), so the
 * file is written in place, read back, and put back as it was if what is there is not what we wrote.
 */
const writeSettings = async ($: EngineInterface, path: string, text: string, expected: string): Promise<boolean> => {
  // Through a symlink to its target (a dotfiles repo), never replacing the link.
  const target = (await $.fs.stat(path, { resolve: true }).catch(() => undefined))?.realPath ?? path
  const unchanged = async (): Promise<boolean> => (await $.fs.read(target).catch(() => undefined)) === expected
  if (!moveArgv(path, target)) {
    if (!(await unchanged())) return false
    try {
      await $.fs.write(target, text)
      if ((await $.fs.read(target).catch(() => undefined)) === text) return true
    } catch {
      // fall through to the put-back
    }
    await $.fs.write(target, expected).catch(() => undefined) // a torn write: the file as it was
    return false
  }
  const tmp = settingsTmp(target, `${(await $.session.id().catch(() => 'x')).slice(0, 8)}-${await nowMs($)}`)
  try {
    const copy = copyModeArgv(target, tmp) // keeps the mode on POSIX; a Windows file has none
    if (copy) await $.process.run(copy).catch(() => undefined)
    await $.fs.write(tmp, text)
    if (await unchanged()) {
      const mv = await $.process.run(moveArgv(tmp, target)!)
      if (mv.exitCode === 0) return true
    }
  } catch {
    // fall through to the cleanup
  }
  await removeFile($, tmp)
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
  const backup = joinPath(dir, BACKUP_FILE)
  const existing = await readBackup($, backup)
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
  if (!(await writeSettings($, path, r.text, text))) {
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
  const backupPath = dir ? joinPath(dir, BACKUP_FILE) : null
  const backup = backupPath ? await readBackup($, backupPath) : null
  if (path && backupPath && backup !== null) {
    const text = await $.fs.read(path).catch(() => undefined)
    const r = restoreStatusLine(typeof text === 'string' ? text : '', backup)
    if (r.done === 'restored') {
      if (await writeSettings($, path, r.text, typeof text === 'string' ? text : '')) {
        await removeFile($, backupPath)
        lines.push(`your status line is back in ${path}`)
      } else lines.push(`could not write ${path}: your status line is still backed up in ${backupPath}`)
    } else if (r.done === 'already') {
      await removeFile($, backupPath)
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

/** The 💸 budget question: asked again until the answer is a positive number. */
async function askBudget($: EngineInterface, run: object): Promise<Answer | null> {
  for (let retry = false; ; retry = true) {
    const a = await askOne($, run, Q.budget(retry))
    if (typeof a !== 'object') return a
    const budget = budgetFrom(a.a)
    if (budget === null) continue
    await saveAnswer($, { budget })
    return null
  }
}

/**
 * The 🎨 style question. Show me asks again with both samples (the ask call takes labels, not previews).
 * Returns the style, or why it stopped. The saved layout is left alone.
 */
async function askStyle($: EngineInterface, run: object): Promise<{ style: Style } | Answer> {
  for (let showMe = false; ; showMe = true) {
    const a = await askOne($, run, Q.style(showMe))
    if (typeof a !== 'object') return a
    if (isShowMe(a.a)) continue
    const style = styleFrom(a.a) ?? 'pacman'
    await saveAnswer($, { style })
    return { style }
  }
}

/** The 📐 layout question (either style has all three). Returns null, or why it stopped. */
async function askLayout($: EngineInterface, run: object): Promise<Answer | null> {
  const l = await askOne($, run, Q.preset())
  if (typeof l !== 'object') return l
  await saveAnswer($, { preset: presetFrom(l.a) ?? 'two' })
  return null
}

/** `/census-setup style` or `budget`: only that question, and only where the line is drawn. */
async function setupOne($: EngineInterface, run: object, only: 'style' | 'budget') {
  await loadSetup($)
  if (!eff.draw) {
    say($, `🧭 census-setup: draw is off, so there is no ${only === 'budget' ? 'cost bar' : 'band'} to ${only === 'budget' ? 'size' : 'style'}. Run /census-setup to turn the status line on`)
    if (setupRun === run) setupRun = null
    return
  }
  if (only === 'budget' && !hasCostBar(eff)) {
    say($, '🧭 census-setup: the status line has no cost bar (the style or layout leaves it out), so there is no budget to set. Run /census-setup style to change the style')
    if (setupRun === run) setupRun = null
    return
  }
  const got = only === 'style' ? await askStyle($, run) : await askBudget($, run)
  if (got === 'superseded') return
  if (setupRun === run) setupRun = null
  if (got === 'dismissed') say($, '🧭 census-setup stopped; what you answered is saved')
  else say($, only === 'style' ? `🧭 census-mod: style is ${eff.style === 'clean' ? "Dave's Nice 'n' Clean" : "Pip's Pac-Man flavour"}` : `🧭 census-mod: the cost bar fills at $${eff.budget}${rawEnv.CLAUDE_COST_BUDGET?.trim() ? ' (CLAUDE_COST_BUDGET overrides this)' : ''}`)
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
    `status line: ${d.statusLineCommand ?? 'none'}${d.ingestBlock ? ' (it records into census)' : ''}${d.settingsInvalid ? ' (settings.json is not valid JSON)' : ''}`,
    `another writer on the store: ${d.otherWriter ? 'yes, active in the last few minutes' : 'no'}`,
    `the census plugin: ${d.censusPlugins.length ? `enabled (${d.censusPlugins.join(', ')})` : 'not enabled'}`,
  ])
  // census and census-mod are alternatives: with the census plugin enabled there would be two writers on one store.
  if (d.censusPlugins.length) {
    const a = await askOne($, run, Q.exclusive(d.censusPlugins))
    if (typeof a !== 'object') return stop(a)
    if (!continueAnyway(a.a)) {
      say($, `🧭 census-setup: census-mod replaces the census plugin — disable it first: ${d.censusPlugins.map(k => `claude plugin disable ${k}`).join('; ')}. Then run /census-setup again`)
      if (setupRun === run) setupRun = null
      return
    }
    say($, '🧭 census-setup: continuing with the census plugin still enabled — two writers on one store; expect muddled liveness')
  }
  let recordMode: 'yes' | 'shadow' | 'no' | null = null
  let replace = false
  if (recordMode === null) {
    const a = await askOne($, run, Q.record(d, Boolean(rawEnv.CENSUS_MOD_STORE?.trim())))
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
  // CENSUS_MOD_STORE outranks the answer: census-mod records to the shadow store, so the status line is still the
  // real store's only writer. Removing it would stop that store before the comparison is done.
  const shadowByEnv = Boolean(rawEnv.CENSUS_MOD_STORE?.trim())
  const keptForShadow = shadowByEnv && recordMode === 'yes' && d.ingestBlock
  let removed: string | undefined
  if (recordMode === 'yes' && d.ingestBlock && !shadowByEnv) {
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
    const st = await askStyle($, run)
    if (typeof st !== 'object' || !('style' in st)) return stop(st)
    const lay = await askLayout($, run)
    if (lay) return stop(lay)
    preset = saved.preset
    if (hasCostBar(eff)) {
      const stopped = await askBudget($, run) // only where the effective segments draw the cost bar
      if (stopped) return stop(stopped)
    }
  }
  const pr = await askOne($, run, Q.pr())
  if (typeof pr !== 'object') return stop(pr)
  await saveAnswer($, { pr: is(pr.a, L.prYes), answeredAt: await nowMs($), offered: true })
  if (setupRun !== run) return
  setupRun = null
  say($, '🧭 census-mod is set up', [
    `recording: ${eff.record === 'yes' ? 'into census (the real store)' : eff.record === 'shadow' ? `shadow store ${eff.shadowDir ?? ''} — the dashboards do not read it; run /census-setup and answer Yes to record into census itself` : 'off'}`,
    `band: ${drawOn ? `on, ${eff.placement === 'below' ? 'below the input' : 'above the input'}, ${eff.style === 'clean' ? `Dave's Nice 'n' Clean, ${CLEAN_PRESETS[preset ?? 'two']}` : PRESETS[preset ?? 'two']}` : 'off'}${rawEnv.CENSUS_STATUSLINE_SEGMENTS?.trim() ? ' (CENSUS_STATUSLINE_SEGMENTS overrides the layout)' : ''}`,
    ...(drawOn && hasCostBar(eff) ? [`cost bar: fills at $${eff.budget}${rawEnv.CLAUDE_COST_BUDGET?.trim() ? ' (CLAUDE_COST_BUDGET overrides your answer)' : ''}`] : []),
    `PR segment: ${eff.pr ? 'on, with gh lookups' : 'gh is never called (run /census-mod:pr-refresh to ask it once); PRs this session creates, readies or merges still show'}`,
    ...(removed ? [`your status line was removed from settings.json; it is backed up in ${removed}`] : []),
    ...(keptForShadow ? ['your status line was kept: CENSUS_MOD_STORE makes census-mod record to a shadow store, so the status line is still the real store\'s writer. Unset it and run /census-setup again to replace it'] : []),
    'undo any time: /census-setup off (it restores a removed status line exactly), or /census-setup to answer again',
  ])
}

function startSetup($: EngineInterface, mode: 'full' | 'offer' | 'budget' | 'style') {
  const run = {}
  setupRun = run
  // After the command has replied: the dialogs follow it rather than holding it open.
  $.clock.after(0, () => void (mode === 'budget' || mode === 'style' ? setupOne($, run, mode) : setup($, run, mode)).catch(() => { if (setupRun === run) setupRun = null }))
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
    ctxWindow: snap.ctxWindow,
    cache: { hitRatio: c.lastRatio, requests: c.requests, warm: isWarm(c, snap.ttl, now * 1000), expiresAt: expires === null ? null : expires / 1000, misses: 0 },
    limits: rateLimitsOf(snap.rateLimits),
    costUsd: snap.costUsd,
    subagentUsd: subagentShown(snap.subagentUsd, snap.costUsd),
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
      await $.command.register({ name: 'census-setup', description: 'Guided census-mod setup: record, draw, style, layout, cost budget, gh. `style` or `budget` asks only that question; `off` stops it.', argumentHint: '[off|style|budget]' }).catch(() => undefined)
      await $.command.register({ name: 'pr-refresh', description: "Ask gh once for this branch's open PR (number, review state) and record it." }).catch(() => undefined)
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
      const before = snap.costUsd
      snap.costUsd = e.cost?.usd ?? snap.costUsd
      if (snap.costUsd !== before) void refreshSubagents($).catch(() => undefined) // a subagent may be what spent it
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
      if (call.tool === 'Bash' && typeof call.command === 'string') {
        await applyGitOperation($, (r as { result?: unknown }).result, call.command)
        if (touchesPr(call.command)) scheduleGh($, 'push')
      }
    })
    return r
  })

  // One gh lookup on demand, whatever the PR answer is; a failure changes nothing (refreshGh's rules).
  on('command.run', { command: 'pr-refresh' }, async $ => {
    if (!interactive || !snap) return { text: 'census-mod: no session to look up a PR for.' }
    const branch = currentBranch()
    const got: { outcome: GhOutcome } = { outcome: 'failed' }
    await quietly(async () => {
      if (Object.keys(rawEnv).length === 0) { rawEnv = await loadEnv($); env = { ...rawEnv } }
      got.outcome = await refreshGh($, 'manual')
    })
    const pr = snap?.pr
    if (got.outcome === 'no-branch') return { text: 'census-mod: this session is not on a branch (detached or no git), so there is no PR to look up.' }
    if (got.outcome !== 'answered') return { text: `census-mod: gh did not answer (is it installed and logged in?), so nothing changed${pr ? `; still showing PR #${pr.number}` : ''}.` }

    return { text: pr ? `census-mod: PR #${pr.number}${pr.reviewState ? ` (${pr.reviewState})` : ''} is open on ${branch ?? 'this branch'}.` : `census-mod: no open PR on ${branch ?? 'this branch'}.` }
  })

  on('command.run', { command: 'census-setup' }, async ($, e) => {
    const args = ((e as unknown as { args?: string }).args ?? '').trim()
    if (args === 'off') {
      setupRun = null
      await quietly(async () => { if (Object.keys(rawEnv).length === 0) { rawEnv = await loadEnv($); env = { ...rawEnv } } await loadSetup($); await turnOff($) })
      return { text: 'census-mod is off. /census-setup to turn it on again.' }
    }
    if (args !== '' && args !== 'budget' && args !== 'style') return { text: 'Usage: /census-setup (guided setup), /census-setup style or budget (one question) or /census-setup off' }
    if (Object.keys(rawEnv).length === 0) { rawEnv = await loadEnv($); env = { ...rawEnv } }
    startSetup($, args === 'budget' ? 'budget' : args === 'style' ? 'style' : 'full')
    return { text: '🧭 census-setup: a few questions follow.' }
  })

  // The ending session's last word: runs under the chain's shared budget, so it carries its own timeout.
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
    if (eff.prHint && interactive && snap) await quietly(() => confirmFromHint($, (e.props as { hint?: unknown }).hint))
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
