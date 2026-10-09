import type { EngineInterface, Register, Timer } from 'claude-code'
import { COUNTER_KEEP_MS, EMPTY_COUNTERS, STORE_PREFIX, TAIL_CMD, addTurn, compacted, counterKey, DEFAULT_TTL, expiresAtMs, isWarm, parseWrites, ttlFromWrites, ttlMs, withTtl } from '../core/cache'
import { INGEST_TIMEOUT_MS, WHICH_ARGV, findSibling, delayFor, endTimeoutMs, ingestArgv, ingestEnv, pointerFiles } from '../core/census'
import type { CensusEnv } from '../core/census'
import { GH_TIMEOUT_MS, ghArgv, ghKey, parsePrList, shouldRefresh, touchesPr } from '../core/gh'
import type { GhEntry, Why } from '../core/gh'
import { COALESCE_MS as GIT_COALESCE_MS, GIT_DIR_ARGV, GIT_STATUS_ARGV, parseStatus, touchesGit, watchPaths, worktreeOf } from '../core/git'
import { configRoot, transcriptPathFor } from '../core/name'
import { buildPayload, modelOf, rateLimitsOf } from '../core/payload'
import type { Event } from '../core/payload'
import { TITLE_ARGV, findProc, lastTitle } from '../core/registry'
import { TONE_COLOR, draw, fit } from '../core/render'
import type { RenderEnv, RenderInput } from '../core/render'
import type { Counters, RateLimit, Snap } from '../core/types'

// The effectful shell: the ONLY file that touches `$`. Decisions live in ../core.
//
// State is module variables plus $.store (counters, gh cache): a hot reload loses the variables, and
// session.start (which re-fires on a reload) rebuilds them. Nothing is kept in $.state, so a /clear
// has nothing to wipe and classic.SessionStart(clear) simply binds the new session.

type Env = CensusEnv & RenderEnv

let env: Env = {}
let interactive: boolean | null = null
let snap: Snap | null = null
let hydrating: Promise<void> | null = null
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
    CENSUS_STATUSLINE_SEGMENTS: await $.env.get('CENSUS_STATUSLINE_SEGMENTS'),
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

async function readName($: EngineInterface) {
  if (!snap?.transcriptPath) return
  try {
    const r = await $.process.run(TITLE_ARGV(snap.transcriptPath))
    if (r.exitCode === 0) snap.sessionName = lastTitle(r.stdout) ?? snap.sessionName
  } catch {
    // keep the last name
  }
}

async function readTtl($: EngineInterface) {
  if (!snap?.transcriptPath) return
  try {
    const r = await $.process.run(['sh', '-c', TAIL_CMD, 'sh', snap.transcriptPath])
    const found = r.exitCode === 0 ? ttlFromWrites(parseWrites(r.stdout)) : null
    if (found) {
      snap.ttl = found
      snap.counters = withTtl(snap.counters, found)
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

async function saveCounters($: EngineInterface) {
  if (snap) await $.store.set(counterKey(snap.sessionId), snap.counters).catch(() => undefined)
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
  if (!snap || snap.cwd !== cwd) return
  const before = snap.git
  snap.git = r && r.exitCode === 0 ? parseStatus(r.stdout) : null
  if (before?.branch !== snap.git?.branch) {
    snap.pr = null
    // The first sight of a branch is not a change of it.
    if (before !== null) record($, 'branch')
    scheduleGh($, 'branch')
  }
  repaint($)
}

function scheduleGh($: EngineInterface, why: Why) {
  if (!interactive) return
  $.clock.after(0, () => void refreshGh($, why).catch(() => undefined))
}

async function refreshGh($: EngineInterface, why: Why) {
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
  for (const t of [ingestTimer, coldTimer, tickTimer, gitTimer]) t?.cancel()
  ingestTimer = coldTimer = tickTimer = gitTimer = null
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
        if (!snap) return
        const gitDir = known ?? (await readGitDir($, snap.cwd))
        if (snap) snap.worktreePath = worktreeOf(gitDir)
        await readName($)
        repaint($)
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
    if (old && event !== 'session.start') closeOld($, old, event.replace('session.', ''))
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
  scheduleGit($)
  record($, event)
  void pruneCounters($, id, await nowMs($))
}

async function isInteractive($: EngineInterface): Promise<boolean> {
  if (interactive !== null) return interactive
  return (await $.session.surfaces().catch(() => [])).length > 0
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
      env = await loadEnv($)
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
      if (Object.keys(env).length === 0) env = await loadEnv($)
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
      // The reads below shell out: off the turn's path.
      $.clock.after(0, () => {
        void (async () => {
          await readTtl($)
          await readName($)
          await saveCounters($)
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

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const inner = await next(e)
    if (e.props.hasSurvey || !interactive || !snap) return inner
    const { Box, Text } = $.ui.resolve(e)
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
    const lines = draw(input).slice(0, Math.max(0, e.props.maxRows)).map(l => fit(l, e.props.bodyColumns))
    if (lines.length === 0) return inner
    return (
      <Box flexDirection="column">
        {lines.map((line, i) => (
          <Box key={`census-${i}`}>
            {line.map((run, j) => (
              <Text key={`r${j}`} color={run.tone ? TONE_COLOR[run.tone] : undefined} wrap="truncate-end">
                {run.t}
              </Text>
            ))}
          </Box>
        ))}
        {inner}
      </Box>
    )
  })
}
