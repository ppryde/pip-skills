import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { SessionRow } from '../types'

const PANE = 'agent-roster'
const TITLE = 'Agents'
const COMMAND = 'roster'
const POLL_MS = 5000
const BRANCH_TTL_MS = 60_000
const PROMPT_MAX = 160
// Idle sessions quieter than this fold behind "show older".
const RECENT_MS = 24 * 3600_000
const SUMMARY_ROWS = 15

// Each live Claude process writes <config dir>/sessions/<pid>.json.
async function configDirOf($: EngineInterface): Promise<string> {
  return (await $.env.get('CLAUDE_CONFIG_DIR')) || `${await $.env.get('HOME')}/.claude`
}

export type ConfigDir = { dir: string; tag?: string }

/** The tag a foreign config dir's rows carry: `.claude-personal` is `personal`, `.claude` is `claude`. */
export function configDirTag(dir: string): string {
  const name = dir.split(/[\\/]/).filter(Boolean).pop() ?? dir

  return name.replace(/^\.claude-/, '').replace(/^\./, '')
}

// "." and ".." folded away, trailing separators dropped: two spellings of one dir compare equal.
function resolved(path: string): string {
  const sep = path.includes('\\') && !path.includes('/') ? '\\' : '/'
  const parts = path.split(/[\\/]/)
  // A root the folding must not climb above: "/", "\\\\" (UNC) or "C:\\".
  let root = ''
  if (parts[0] === '' && parts[1] === '' && parts.length > 2) {
    root = sep + sep
    parts.splice(0, 2)
  } else if (parts[0] === '' && parts.length > 1) {
    root = sep
    parts.shift()
  } else if (/^[A-Za-z]:$/.test(parts[0]!) && parts.length > 1) {
    root = parts.shift() + sep
  }
  const out: string[] = []
  for (const part of parts) {
    if (part === '.' || part === '') continue
    if (part !== '..') out.push(part)
    else if (out.length > 0 && out.at(-1) !== '..') out.pop()
    else if (!root) out.push('..')
  }

  return root + out.join(sep) || '.'
}

/**
 * The config dirs to read, from `ROSTER_CONFIG_DIRS`. The mod cannot see the
 * platform, so it splits on ":" unless an entry starts with a drive letter
 * (`C:\`) or is a UNC path (`\\server\share`), then on ";". `~` (or `~/`, `~\`) is HOME. Deduped by resolved path; the session's
 * own dir is always read, first and untagged, listed or not. Unset or blank: the own dir alone.
 */
export function resolveConfigDirs(raw: string | undefined, home: string, own: string): ConfigDir[] {
  if (!raw?.trim()) return [{ dir: own }]
  const separator = /(^|;)([A-Za-z]:[\\/]|\\\\)/.test(raw) ? ';' : ':'
  // Windows paths ignore case: "C:\\U" and "c:\\u" are one dir.
  const key = (dir: string) => (separator === ';' ? dir.toLowerCase() : dir)
  const seen = new Set<string>([key(resolved(own))])
  // Always first: a list must not hide the person's own sessions.
  const dirs: ConfigDir[] = [{ dir: own }]
  for (const entry of raw.split(separator)) {
    const text = entry.trim()
    if (!text) continue
    const dir = resolved(/^~([\\/]|$)/.test(text) ? home + text.slice(1) : text)
    if (seen.has(key(dir))) continue
    seen.add(key(dir))
    dirs.push({ dir, tag: configDirTag(dir) })
  }

  return dirs
}

const sessions = atom({ plugin: 'agent-roster', key: 'sessions' } as const, {
  rows: [],
  checkedAt: 0,
})
const pendingKill = atom({ plugin: 'agent-roster', key: 'pendingKill' } as const, null)
const showOlder = atom({ plugin: 'agent-roster', key: 'showOlder' } as const, false)
const repoTab = atom({ plugin: 'agent-roster', key: 'repoTab' } as const, null)

// Waiting first: it needs you. Then busy, then the rest.
const RANK: Record<string, number> = { waiting: 0, busy: 1 }

// Caches only: a reload starts them empty and the next poll refills them.
const transcriptPaths = new Map<string, string>()
// sessionId → when to look for a missing transcript again.
const transcriptMisses = new Map<string, number>()
const TRANSCRIPT_RETRY_MS = 60_000
const facts = new Map<string, { mtimeMs: number; facts: TranscriptFacts }>()
const branches = new Map<string, { at: number; branch?: string }>()
// A folder's repo never changes: resolved once.
const gitRepos = new Map<string, { repo: string; worktree?: string }>()

export type TranscriptFacts = { title?: string; prompt?: string; promptAt?: number }

export function repoOf(cwd: string): { repo: string; worktree?: string } {
  const parts = cwd.split('/').filter(Boolean)
  const at = parts.lastIndexOf('worktrees')
  if (at >= 2 && parts[at - 1] === '.claude') {
    return { repo: parts[at - 2] ?? cwd, worktree: parts[at + 1] }
  }

  return { repo: parts[parts.length - 1] ?? cwd }
}

/** The folder name Claude Code files a project's transcripts under. */
export function projectSlug(cwd: string): string {
  return cwd.replace(/[^A-Za-z0-9]/g, '-')
}

export function toRow(raw: unknown): SessionRow | undefined {
  if (typeof raw !== 'object' || raw === null) return undefined
  const d = raw as Record<string, unknown>
  // pid 0 or 1 would make `kill` signal a process group or init: never a session.
  const pid = d.pid
  if (typeof pid !== 'number' || !Number.isInteger(pid) || pid <= 1 || typeof d.cwd !== 'string') return undefined
  const tmux = typeof d.tmux === 'string' ? d.tmux.split(':')[0] : undefined

  return {
    pid,
    sessionId: String(d.sessionId ?? ''),
    tmux: tmux || undefined,
    cwd: d.cwd,
    ...repoOf(d.cwd),
    status: String(d.status ?? 'unknown'),
    waitingFor: typeof d.waitingFor === 'string' ? d.waitingFor : undefined,
    kind: String(d.kind ?? 'interactive'),
    lastActive: Number(d.updatedAt ?? d.statusUpdatedAt ?? 0),
  }
}

function clip(text: string): string {
  const flat = text.replace(/\s+/g, ' ').trim()
  return flat.length > PROMPT_MAX ? `${flat.slice(0, PROMPT_MAX - 1)}…` : flat
}

/** The text a person typed, or undefined for markup (a slash command's record) and non-text. */
function typedText(content: unknown): string | undefined {
  const text =
    typeof content === 'string'
      ? content
      : Array.isArray(content)
        ? (content.find(b => b?.type === 'text') as { text?: string } | undefined)?.text
        : undefined
  if (!text || text.trimStart().startsWith('<')) return undefined

  return text
}

/**
 * From a transcript's title and human-prompt rows: its title (a `/rename`
 * wins over the AI one) and the last prompt the person typed, with its time.
 * Teammate messages and task notifications are not `origin.kind: human`.
 */
export function transcriptFacts(lines: string): TranscriptFacts {
  let custom: string | undefined
  let ai: string | undefined
  let prompt: string | undefined
  let promptAt: number | undefined
  const rows = lines.trimEnd().split('\n')
  for (let i = rows.length - 1; i >= 0; i--) {
    let row: Record<string, any>
    try {
      row = JSON.parse(rows[i] ?? '')
    } catch {
      continue
    }
    if (row.type === 'custom-title' && custom === undefined && typeof row.customTitle === 'string') {
      custom = row.customTitle
    } else if (row.type === 'ai-title' && ai === undefined && typeof row.aiTitle === 'string') {
      ai = row.aiTitle
    } else if (prompt === undefined && row.type === 'user' && row.origin?.kind === 'human') {
      const text = typedText(row.message?.content)
      if (text) {
        prompt = clip(text)
        promptAt = Date.parse(row.timestamp) || undefined
      }
    }
  }
  const title = custom ?? ai

  return { title: title ? clip(title) : undefined, prompt, promptAt }
}

export function sorted(rows: SessionRow[]): SessionRow[] {
  return [...rows].sort(
    (a, b) => (RANK[a.status] ?? 2) - (RANK[b.status] ?? 2) || b.lastActive - a.lastActive,
  )
}

export function ago(then: number, now: number): string {
  const s = Math.max(0, Math.round((now - then) / 1000))
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.round(s / 60)}m`
  if (s < 86400) return `${Math.round(s / 3600)}h`

  return `${Math.round(s / 86400)}d`
}

export function grouped(rows: SessionRow[], now: number) {
  const idle = rows.filter(r => r.status !== 'waiting' && r.status !== 'busy')

  return {
    waiting: rows.filter(r => r.status === 'waiting'),
    busy: rows.filter(r => r.status === 'busy'),
    recent: idle.filter(r => now - r.lastActive < RECENT_MS),
    older: idle.filter(r => now - r.lastActive >= RECENT_MS),
  }
}

export type RepoTab = { repo: string; waiting: number; busy: number; total: number; lastActive: number }

/** One tab per repo (worktrees under their repo): those needing you first, then working, then recent. */
export function repoTabs(rows: SessionRow[]): RepoTab[] {
  const tabs = new Map<string, RepoTab>()
  for (const r of rows) {
    const tab = tabs.get(r.repo) ?? { repo: r.repo, waiting: 0, busy: 0, total: 0, lastActive: 0 }
    tab.total += 1
    if (r.status === 'waiting') tab.waiting += 1
    if (r.status === 'busy') tab.busy += 1
    tab.lastActive = Math.max(tab.lastActive, r.lastActive)
    tabs.set(r.repo, tab)
  }

  return [...tabs.values()].sort(
    (a, b) =>
      Number(b.waiting > 0) - Number(a.waiting > 0) ||
      Number(b.busy > 0) - Number(a.busy > 0) ||
      b.lastActive - a.lastActive,
  )
}

export type TabMark = { text: string; color: string }

/** A tab's counts beside its name: red ? waiting, green ● working, grey ○ idle; zeros left out. */
export function tabMarks(tab: Pick<RepoTab, 'waiting' | 'busy' | 'total'>): TabMark[] {
  const idle = tab.total - tab.waiting - tab.busy
  const marks: (TabMark | false)[] = [
    tab.waiting > 0 && { text: `?${tab.waiting}`, color: 'red' },
    tab.busy > 0 && { text: `●${tab.busy}`, color: 'green' },
    idle > 0 && { text: `○${idle}`, color: 'gray' },
  ]

  return marks.filter((m): m is TabMark => m !== false)
}

export function headline(rows: SessionRow[]): string {
  const waiting = rows.filter(r => r.status === 'waiting').length
  const busy = rows.filter(r => r.status === 'busy').length

  return `${waiting} need you · ${busy} working · ${rows.length - waiting - busy} idle`
}

const label = (r: SessionRow) => r.title ?? (r.worktree ? `${r.repo}/${r.worktree}` : r.repo)
const nameOf = (r: SessionRow) => r.tmux ?? `pid ${r.pid}`

/** The roster as plain text for Remote Control: sections, one or two lines a session. */
export function summary(rows: SessionRow[], now: number, warnings: string[] = []): string {
  const { waiting, busy, recent, older } = grouped(rows, now)
  const lines = [headline(rows)]
  let budget = SUMMARY_ROWS
  const section = (heading: string, list: SessionRow[]) => {
    if (list.length === 0 || budget <= 0) return
    lines.push('', heading)
    for (const r of list.slice(0, budget)) {
      const why = r.status === 'waiting' && r.waitingFor ? ` · ${r.waitingFor}` : r.note ? ` · ${r.note}` : ''
      const account = r.account ? ` · ${r.account}` : ''
      lines.push(`• ${label(r)} — ${nameOf(r)} · ${r.repo} · ${ago(r.lastActive, now)}${why}${account}`)
      if (r.prompt) lines.push(`   you${r.promptAt ? ` ${ago(r.promptAt, now)}` : ''}: ${r.prompt}`)
    }
    budget -= list.length
  }
  section('NEEDS YOU', waiting)
  section('WORKING', busy)
  section('IDLE, LAST 24H', recent)
  if (older.length) lines.push('', `+ ${older.length} idle for over a day`)
  if (warnings.length) lines.push('', ...warnings.map(w => `! could not read ${w}`))

  return lines.join('\n')
}

async function transcriptOf($: EngineInterface, configDir: string, row: SessionRow) {
  if (!row.sessionId) return undefined
  const known = transcriptPaths.get(row.sessionId)
  if (known) return known
  // A session before its first prompt has no transcript yet: look again later.
  if ((transcriptMisses.get(row.sessionId) ?? 0) > Date.now()) return undefined
  const guess = `${configDir}/projects/${projectSlug(row.cwd)}/${row.sessionId}.jsonl`
  let path: string | undefined = (await $.fs.exists(guess)) ? guess : undefined
  if (!path) {
    // The session moved since launch (into a worktree, say): its transcript stays where it began.
    const found = await $.process
      .run(['find', `${configDir}/projects`, '-maxdepth', '2', '-name', `${row.sessionId}.jsonl`])
      .catch(() => undefined)
    path = found?.stdout.split('\n')[0]?.trim() || undefined
  }
  if (path) transcriptPaths.set(row.sessionId, path)
  else transcriptMisses.set(row.sessionId, Date.now() + TRANSCRIPT_RETRY_MS)

  return path
}

async function factsOf($: EngineInterface, configDir: string, row: SessionRow): Promise<TranscriptFacts> {
  const path = await transcriptOf($, configDir, row)
  if (!path) return {}
  const stat = await $.fs.stat(path).catch(() => undefined)
  if (!stat) return {}
  const cached = facts.get(path)
  if (cached && cached.mtimeMs === stat.mtimeMs) return cached.facts
  const grep = await $.process
    .run([
      'grep',
      '-h',
      '-e',
      '"type":"ai-title"',
      '-e',
      '"type":"custom-title"',
      '-e',
      '"origin":{"kind":"human"}',
      path,
    ])
    .catch(() => undefined)
  const found = grep ? transcriptFacts(grep.stdout) : {}
  facts.set(path, { mtimeMs: stat.mtimeMs, facts: found })

  return found
}

/** The repo a folder's git says it is (a sibling worktree under its main checkout); else by path. */
export function repoFromGit(cwd: string, top: string, commonDir: string): { repo: string; worktree?: string } {
  if (!commonDir.endsWith('/.git')) return repoOf(cwd)
  const main = commonDir.slice(0, -'/.git'.length)
  const name = (path: string) => path.split('/').filter(Boolean).pop() ?? path

  return top && top !== main ? { repo: name(main), worktree: name(top) } : { repo: name(main) }
}

async function gitRepoOf($: EngineInterface, cwd: string) {
  const known = gitRepos.get(cwd)
  if (known) return known
  const git = await $.process
    .run(['git', '-C', cwd, 'rev-parse', '--path-format=absolute', '--show-toplevel', '--git-common-dir'])
    .catch(() => undefined)
  const [top = '', common = ''] = git?.exitCode === 0 ? git.stdout.trim().split('\n') : []
  const found = repoFromGit(cwd, top, common)
  gitRepos.set(cwd, found)

  return found
}

async function branchOf($: EngineInterface, cwd: string) {
  const cached = branches.get(cwd)
  if (cached && Date.now() - cached.at < BRANCH_TTL_MS) return cached.branch
  const git = await $.process
    .run(['git', '-C', cwd, 'branch', '--show-current'])
    .catch(() => undefined)
  const branch = git?.exitCode === 0 ? git.stdout.trim() || undefined : undefined
  branches.set(cwd, { at: Date.now(), branch })

  return branch
}

/**
 * The registry's entries. A missing folder (no session has run yet) is an
 * empty registry; any other failure rejects, so the last good roster stays up
 * with the reason instead of an empty one.
 */
export async function listRegistry($: EngineInterface, dir: string) {
  try {
    return await $.fs.list(dir)
  } catch (err) {
    if (!(await $.fs.exists(dir).catch(() => true))) return []
    throw err
  }
}

/**
 * One pid in two registries means one of them is stale (pids are unique on a
 * host, and a crashed session's file outlives it): the live process keeps
 * touching its own, so the most recently active row wins, the earlier dir on a tie.
 */
export function newestPerPid<T extends { row: SessionRow }>(found: T[]): T[] {
  const newest = new Map<number, T>()
  for (const f of found) {
    const held = newest.get(f.row.pid)
    if (!held || f.row.lastActive > held.row.lastActive) newest.set(f.row.pid, f)
  }

  return found.filter(f => newest.get(f.row.pid) === f)
}

async function scan($: EngineInterface): Promise<{ rows: SessionRow[]; warnings: string[] }> {
  const dirs = resolveConfigDirs(
    (await $.env.get('ROSTER_CONFIG_DIRS')) || undefined,
    (await $.env.get('HOME')) ?? '',
    await configDirOf($),
  )
  const found: { row: SessionRow; configDir: string }[] = []
  const warnings: string[] = []
  const unlisted = new Set<string>()
  for (const { dir: configDir, tag } of dirs) {
    const name = tag ?? 'own dir'
    let entries: Awaited<ReturnType<typeof listRegistry>>
    try {
      entries = await listRegistry($, `${configDir}/sessions`)
    } catch (err) {
      // One unreadable dir must not hide the others' sessions.
      warnings.push(`${name}: ${String(err).slice(0, 120)}`)
      unlisted.add(configDir)
      continue
    }
    for (const entry of entries) {
      if (!entry.name.endsWith('.json')) continue
      const file = `${configDir}/sessions/${entry.name}`
      let text: unknown
      try {
        text = await $.fs.read(file)
      } catch (err) {
        // Gone since the listing (a session ended) is routine; anything else is worth a warning.
        if ((await $.fs.exists(file).catch(() => true)) && !warnings.some(w => w.startsWith(`${name}: `))) {
          warnings.push(`${name}: ${String(err).slice(0, 120)}`)
        }
        continue
      }
      if (typeof text !== 'string') continue
      try {
        const row = toRow(JSON.parse(text))
        if (row) found.push({ row: tag ? { ...row, account: tag } : row, configDir })
      } catch {
        // A file caught mid-write; the next poll reads it whole.
      }
    }
  }
  // The registry outlives crashed processes, and their pids get reused: keep
  // only pids still running Claude.
  // Every dir failing is a failed scan: the last good roster stays up with the reason.
  if (unlisted.size === dirs.length) throw new Error(warnings.join('; '))
  const alive = await liveClaudePids(
    $,
    found.map(f => f.row.pid),
  )
  const live = newestPerPid(found.filter(f => alive.has(f.row.pid)))

  const registered = await Promise.all(
    live.map(async ({ row, configDir }) => {
      // One session's details failing must not take the others down.
      try {
        return {
          ...row,
          ...(await gitRepoOf($, row.cwd)),
          branch: await branchOf($, row.cwd),
          ...(await factsOf($, configDir, row)),
        }
      } catch {
        return row
      }
    }),
  )
  const strays = await strayPanes($, {
    pids: new Set(live.map(f => f.row.pid)),
    tmuxNames: new Set(live.flatMap(f => (f.row.tmux ? [f.row.tmux] : []))),
  }, dirs.map(d => d.dir))

  return { rows: [...registered, ...strays], warnings }
}

// What tmux reports per pane, tab-separated, for the unregistered-session sweep.
const PANE_FORMAT = '#{session_name}\t#{pane_pid}\t#{pane_current_command}\t#{pane_current_path}\t#{window_activity}'
// Claude Code's binary runs under its version as its name (2.1.289), or as `claude`.
const CLAUDE_COMMAND = /^(\d+\.\d+\.\d+|claude)$/

/** From `ps -o pid=,comm=` output: the pids whose command is Claude Code (basename). */
export function claudePidsIn(psOutput: string): Set<number> {
  const pids = new Set<number>()
  for (const line of psOutput.split('\n')) {
    const match = /^\s*(\d+)\s+(.+?)\s*$/.exec(line)
    if (!match) continue
    const pid = Number(match[1])
    const command = match[2]!.split('/').pop() ?? ''
    if (pid > 1 && CLAUDE_COMMAND.test(command)) pids.add(pid)
  }

  return pids
}

async function liveClaudePids($: EngineInterface, pids: number[]): Promise<Set<number>> {
  if (pids.length === 0) return new Set()
  const ps = await $.process.run(['ps', '-o', 'pid=,comm=', '-p', pids.join(',')])

  return claudePidsIn(ps.stdout)
}

const STARTUP_PROMPT = 'at a startup prompt (not registered yet)'

/**
 * A row from the tmux sweep, not the registry. Its pid is the pane's first
 * process, which may be a shell above Claude, so it is never offered a kill.
 */
export function isStray(r: SessionRow): boolean {
  return r.sessionId === '' && (r.waitingFor === STARTUP_PROMPT || r.note !== undefined)
}

const AGENTS_VIEW = 'agents view'
const inAnotherAccount = (tag: string) => `running in another account (${tag}) — set ROSTER_CONFIG_DIRS to list it`

/** `claude agents`, the agents view, by its args. */
export const isAgentsViewArgs = (args: string): boolean => /^\S+\s+agents(\s|$)/.test(args)

/** From `ps -o pid=,args=` output: the pids running Claude's agents view (`claude agents`). */
export function agentsViewPidsIn(psOutput: string): Set<number> {
  const pids = new Set<number>()
  for (const line of psOutput.split('\n')) {
    const match = /^\s*(\d+)\s+(.*)$/.exec(line)
    if (match && isAgentsViewArgs(match[2] ?? '')) pids.add(Number(match[1]))
  }

  return pids
}

export type Proc = { ppid: number; etimeMs: number | null; args: string }

/** `ps` elapsed time, `[[dd-]hh:]mm:ss`, in ms; null when it is not that. */
export function parseEtime(etime: string): number | null {
  const m = /^(?:(\d+)-)?(?:(\d+):)?(\d+):(\d+)$/.exec(etime.trim())
  if (!m) return null
  const [, d, h, mm, ss] = m

  return ((Number(d ?? 0) * 24 + Number(h ?? 0)) * 3600 + Number(mm) * 60 + Number(ss)) * 1000
}

/** From `ps -ax -o pid=,ppid=,etime=,args=`: every process by pid. */
export function procsIn(psOutput: string): Map<number, Proc> {
  const procs = new Map<number, Proc>()
  for (const line of psOutput.split('\n')) {
    const m = /^\s*(\d+)\s+(\d+)\s+(\S+)\s+(.*)$/.exec(line)
    if (m) procs.set(Number(m[1]), { ppid: Number(m[2]), etimeMs: parseEtime(m[3] ?? ''), args: m[4] ?? '' })
  }

  return procs
}

const isClaudeProc = (p: Proc): boolean => CLAUDE_COMMAND.test((p.args.split(/\s+/)[0] ?? '').split('/').pop() ?? '')

/**
 * The Claude process for a tmux pane pid. A pane's first process is often a shell above Claude, whose pid no
 * registry knows: look down the tree for the nearest Claude. A pane that is Claude itself, has none below it,
 * or is not in `ps` resolves to its own pid.
 */
export function claudePidFor(procs: ReadonlyMap<number, Proc>, panePid: number): number {
  const self = procs.get(panePid)
  if (self && isClaudeProc(self)) return panePid
  const children = new Map<number, number[]>()
  for (const [pid, p] of procs) children.set(p.ppid, [...(children.get(p.ppid) ?? []), pid])
  const queue = [...(children.get(panePid) ?? [])]
  for (let seen = 0; queue.length > 0 && seen < 200; seen++) {
    const pid = queue.shift() as number
    const p = procs.get(pid)
    if (p && isClaudeProc(p)) return pid
    queue.push(...(children.get(pid) ?? []))
  }

  return panePid
}

const START_TOLERANCE_MS = 120_000

/**
 * Does a registry record belong to the live process? Its `startedAt` (epoch ms) should be about `now` minus the
 * process's elapsed time; a record a crash left behind, whose pid was reused, is days off. With nothing to
 * compare (no startedAt, or no etime) the record cannot be told from a reused pid's, so it does not match.
 */
export function startMatches(startedAt: unknown, etimeMs: number | null, now: number): boolean {
  if (typeof startedAt !== 'number' || etimeMs === null) return false

  return Math.abs(now - etimeMs - startedAt) <= START_TOLERANCE_MS
}

/**
 * The other `.claude*` dirs under HOME, whose registries this session is not
 * reading: a pane with no entry here may be registered in one of them.
 */
export function otherClaudeDirs(home: string, names: readonly string[], listed: readonly string[]): string[] {
  const skip = new Set(listed.map(resolved))

  return names.filter(n => n.startsWith('.claude')).map(n => `${home}/${n}`).filter(dir => !skip.has(resolved(dir)))
}

/**
 * Panes running Claude with no registry entry: a session held at a startup
 * prompt (trusting a folder, a login) has not registered yet, and it is
 * exactly one that waits on the person.
 */
export function strayRows(
  panes: string,
  registered: { pids: ReadonlySet<number>; tmuxNames: ReadonlySet<string> },
  context: { elsewhere?: ReadonlyMap<number, string>; agentsView?: ReadonlySet<number> } = {},
): SessionRow[] {
  const rows: SessionRow[] = []
  for (const line of panes.split('\n')) {
    const [tmux, pidText, command, cwd, activity] = line.split('\t')
    const pid = Number(pidText)
    // A registered session whose pane holds a shell above Claude shows the
    // shell's pid here: its tmux name still says it is listed already.
    const isListed = registered.pids.has(pid) || registered.tmuxNames.has(tmux ?? '')
    if (!tmux || !cwd || !(pid > 1) || isListed || !CLAUDE_COMMAND.test(command ?? '')) continue
    const account = context.elsewhere?.get(pid)
    const note = account !== undefined ? inAnotherAccount(account) : context.agentsView?.has(pid) ? AGENTS_VIEW : undefined
    rows.push({
      pid,
      sessionId: '',
      tmux,
      cwd,
      ...repoOf(cwd),
      // A note explains a pane that is not waiting on anyone; only a true stray is a startup prompt.
      ...(note !== undefined ? { status: 'idle', note } : { status: 'waiting', waitingFor: STARTUP_PROMPT }),
      kind: 'interactive',
      lastActive: Number(activity) * 1000 || 0,
    })
  }

  return rows
}

async function strayPanes(
  $: EngineInterface,
  registered: { pids: ReadonlySet<number>; tmuxNames: ReadonlySet<string> },
  listedDirs: readonly string[],
): Promise<SessionRow[]> {
  const sweeps: string[] = []
  for (const socket of await tmuxSockets($)) {
    const panes = await $.process
      .run(['tmux', '-L', socket, 'list-panes', '-a', '-F', PANE_FORMAT])
      .catch(() => undefined)
    if (panes?.exitCode === 0) sweeps.push(panes.stdout)
  }
  // Only a pane nothing here lists can be a stray: the rest need no extra look.
  const candidates = [...new Set(sweeps.flatMap(s => strayRows(s, registered).map(r => r.pid)))]
  if (candidates.length === 0) return []
  // One ps for every process: a pane's pid is often a shell, and the Claude under it is what a registry knows.
  const ps = await $.process.run(['ps', '-ax', '-o', 'pid=,ppid=,etime=,args=']).catch(() => undefined)
  const procs = ps?.exitCode === 0 ? procsIn(ps.stdout) : new Map<number, Proc>()
  const claudeOf = new Map(candidates.map(pid => [pid, claudePidFor(procs, pid)] as const))
  const context = {
    elsewhere: await registeredElsewhere($, claudeOf, procs, listedDirs),
    agentsView: new Set(candidates.filter(pid => isAgentsViewArgs(procs.get(claudeOf.get(pid) ?? pid)?.args ?? ''))),
  }

  return sweeps.flatMap(s => strayRows(s, registered, context))
}

/**
 * Panes whose Claude is registered in another `.claude*` dir under HOME, by that dir's tag. The record must be
 * the live process's own (its start time agrees with the process's), or a dead session's leftover file would
 * label whatever process reused its pid. Keyed by the pane's pid.
 */
async function registeredElsewhere(
  $: EngineInterface,
  claudeOf: ReadonlyMap<number, number>,
  procs: ReadonlyMap<number, Proc>,
  listedDirs: readonly string[],
): Promise<Map<number, string>> {
  const found = new Map<number, string>()
  const home = (await $.env.get('HOME')) ?? ''
  if (!home) return found
  const names = (await $.fs.list(home).catch(() => [])).map(e => e.name)
  const now = Date.now()
  for (const dir of otherClaudeDirs(home, names, listedDirs)) {
    for (const [panePid, pid] of claudeOf) {
      if (found.has(panePid)) continue
      const text = await $.fs.read(`${dir}/sessions/${pid}.json`).catch(() => undefined)
      let record: { pid?: unknown; startedAt?: unknown } | undefined
      try {
        record = typeof text === 'string' ? (JSON.parse(text) as { pid?: unknown; startedAt?: unknown }) : undefined
      } catch {
        record = undefined
      }
      if (!record || typeof record !== 'object' || (record.pid !== undefined && record.pid !== pid)) continue
      if (startMatches(record.startedAt, procs.get(pid)?.etimeMs ?? null, now)) found.set(panePid, configDirTag(dir))
    }
  }

  return found
}

// One scan at a time: a slow scan finishing after a newer one would put older rows back.
let scanning: Promise<void> | undefined

function refresh($: EngineInterface): Promise<void> {
  scanning ??= rescan($).finally(() => {
    scanning = undefined
  })

  return scanning
}

async function rescan($: EngineInterface) {
  let rows: SessionRow[]
  let warnings: string[]
  try {
    const scanned = await scan($)
    rows = sorted(scanned.rows)
    warnings = scanned.warnings
  } catch (err) {
    // Keep the last good roster on screen and say why it is stale.
    await update($, sessions, held => ({ ...held, error: String(err).slice(0, 200) }))
    return
  }
  const selfId = await $.session.id()
  await update($, sessions, () => ({ rows, checkedAt: Date.now(), selfId, warnings }))
  const waiting = rows.filter(r => r.status === 'waiting').length
  $.ui.status(waiting ? `agents: ${waiting} waiting` : undefined)
}

/** A refresh the person asked for: branches re-read now, not when their minute is up. */
async function refreshNow($: EngineInterface) {
  // A scan already running would put the branches it read back after a clear.
  await scanning?.catch(() => undefined)
  branches.clear()
  await rescanAfterCurrent($)
}

/**
 * A fresh scan after any one already running: that one began before a kill or
 * a branch switch, so joining it would show the old state for another poll.
 */
async function rescanAfterCurrent($: EngineInterface) {
  await scanning?.catch(() => undefined)
  await refresh($).catch(() => undefined)
}

/** The sessions a `/roster kill` argument names: a tmux name or a pid. */
export function matchTarget(rows: SessionRow[], target: string): SessionRow[] {
  return rows.filter(r => r.tmux === target || String(r.pid) === target)
}

/** Every tmux server socket of this user: the default one first, any other under the tmux dir after. */
async function tmuxSockets($: EngineInterface): Promise<string[]> {
  const uid = await $.process
    .run(['id', '-u'])
    .then(r => r.stdout.trim())
    .catch(() => '')
  const listed = uid ? await $.fs.list(`/tmp/tmux-${uid}`).catch(() => []) : []

  return [...new Set(['default', ...listed.map(s => s.name)])]
}

/** The pids of every pane in a tmux session on one socket; undefined when it is not there. */
async function panePids($: EngineInterface, socket: string, tmux: string): Promise<number[] | undefined> {
  const panes = await $.process
    .run(['tmux', '-L', socket, 'list-panes', '-s', '-t', `=${tmux}`, '-F', '#{pane_pid}'])
    .catch(() => undefined)

  return panes?.exitCode === 0 ? panes.stdout.split('\n').filter(Boolean).map(Number) : undefined
}

/** The tmux socket whose session of this name has the session's own pid in a pane. */
async function socketOf($: EngineInterface, r: SessionRow): Promise<string | undefined> {
  if (!r.tmux) return undefined
  for (const socket of await tmuxSockets($)) {
    // A name alone is not enough: two sockets can each hold a session of that name.
    if ((await panePids($, socket, r.tmux))?.includes(r.pid)) return socket
  }

  return undefined
}

/**
 * Whether `kill-session` may end the target's whole tmux session. Only when
 * this session is known and the target holds it neither by pane (a shell above
 * Claude shows the shell's pid there, so that alone is not enough) nor by tmux
 * name; otherwise only the target process is signalled.
 */
export function mayKillTmuxSession(
  target: { tmux?: string },
  targetPanes: readonly number[],
  self: { pid: number; tmux?: string } | undefined,
): boolean {
  if (!self) return false
  if (targetPanes.includes(self.pid)) return false

  return !(self.tmux && self.tmux === target.tmux)
}

/**
 * Ends a session: its whole tmux session when it has one (so no orphaned
 * shell pane is left), else SIGTERM to its pid. Never the session it runs in,
 * never a pid that stopped being Claude since the roster looked.
 */
async function killSession($: EngineInterface, r: SessionRow): Promise<string> {
  const name = nameOf(r)
  const selfId = await $.session.id()
  const self = selfId ? (await read($, sessions)).rows.find(s => s.sessionId === selfId) : undefined
  if ((selfId && r.sessionId === selfId) || r.pid === self?.pid) return `Refused: ${name} is this session.`
  if (isStray(r)) {
    return `Refused: ${name} is not a session of this registry (${r.note ?? 'at a startup prompt, not registered yet'}), so its pid may be a shell; open it, or close its pane.`
  }
  if (!(await liveClaudePids($, [r.pid])).has(r.pid)) {
    return `Refused: pid ${r.pid} is no longer a Claude session; refresh and try again.`
  }
  const socket = await socketOf($, r)
  const panes = socket && r.tmux ? ((await panePids($, socket, r.tmux)) ?? []) : []
  const isWholeSession = Boolean(socket && r.tmux) && mayKillTmuxSession(r, panes, self)
  const run = isWholeSession
    ? await $.process.run(['tmux', '-L', socket!, 'kill-session', '-t', `=${r.tmux}`])
    : await $.process.run(['kill', String(r.pid)])
  if (run.exitCode !== 0) return `Could not kill ${name}: ${run.stderr.trim() || `exit ${run.exitCode}`}`

  return isWholeSession ? `Killed tmux session ${name} (socket ${socket}).` : `Sent SIGTERM to ${name}.`
}

async function killFromPane($: EngineInterface, r: SessionRow) {
  const message = await killSession($, r).catch(err => `Could not kill: ${String(err)}`)
  await update($, pendingKill, () => null)
  $.ui.toast(message)
  await rescanAfterCurrent($)
}

// What may be spliced into the shell line, the AppleScript string and the
// link below: no quotes or spaces, no leading dash, not `.` or `..`.
const SAFE_NAME = /^(?!-)(?!\.+$)[\w.-]+$/
const SAFE_NONCE = /^[0-9a-f-]{16,64}$/

/** The shell line that attaches a terminal to one tmux session on one socket. */
export function attachCommand(socket: string, name: string): string | undefined {
  if (!SAFE_NAME.test(socket) || !SAFE_NAME.test(name)) return undefined

  return `tmux -L ${socket} attach -t '=${name}'`
}

/**
 * The link the VS Code helper (`vscode/`) answers with a terminal tab attached
 * to the session. `nonce` is a one-time token the roster leaves in a file the
 * helper reads: a link a web page opens cannot carry it, so it does nothing.
 */
export function vscodeUri(socket: string, name: string, nonce: string): string | undefined {
  if (!SAFE_NAME.test(socket) || !SAFE_NAME.test(name) || !SAFE_NONCE.test(nonce)) return undefined

  return `vscode://pip.agent-roster-vscode/attach?socket=${socket}&name=${name}&nonce=${nonce}`
}

// `code`, wherever Homebrew or the app put it.
const CODE_CLIS = ['/opt/homebrew/bin/code', '/usr/local/bin/code']
// Where the helper has each open VS Code window name its folders, and where
// the roster leaves the one-time token a link must carry.
const VSCODE_WINDOWS_DIR = '.cache/agent-roster/vscode-windows'
const VSCODE_NONCE_FILE = '.cache/agent-roster/attach-nonce'
// A window's extension host runs as a VS Code helper process.
// (VS Code, Code - Insiders, VSCodium: "… Helper").
const VSCODE_HOST = /(Code|Codium)[^/]* Helper/

export type VscodeWindow = { pid: number; folders: string[] }

/** The folder of a live window showing the target repo, matched by repo root (worktrees and subfolders alike). */
export function windowFolderFor(
  windows: VscodeWindow[],
  alive: ReadonlySet<number>,
  rootOf: ReadonlyMap<string, string>,
  targetRoot: string,
): string | undefined {
  for (const w of windows) {
    if (!alive.has(w.pid)) continue
    const folder = w.folders.find(f => (rootOf.get(f) ?? f) === targetRoot)
    if (folder) return folder
  }

  return undefined
}

/** The open VS Code window folder showing this session's repo, if the helper reported one. */
async function vscodeFolderFor($: EngineInterface, r: SessionRow): Promise<string | undefined> {
  const dir = `${await $.env.get('HOME')}/${VSCODE_WINDOWS_DIR}`
  const windows: VscodeWindow[] = []
  for (const entry of await $.fs.list(dir).catch(() => [])) {
    if (!entry.name.endsWith('.json')) continue
    try {
      const w = JSON.parse(String(await $.fs.read(`${dir}/${entry.name}`))) as VscodeWindow
      if (typeof w.pid === 'number' && Array.isArray(w.folders)) windows.push(w)
    } catch {
      // Half-written or foreign: skip it.
    }
  }
  if (windows.length === 0) return undefined
  // A window that crashed leaves its file, and its pid gets reused: only live
  // VS Code extension hosts count.
  const ps = await $.process.run(['ps', '-o', 'pid=,comm=', '-p', windows.map(w => w.pid).join(',')])
  const alive = new Set(
    ps.stdout
      .split('\n')
      .map(line => /^\s*(\d+)\s+(.*)$/.exec(line))
      .filter((m): m is RegExpExecArray => m !== null && VSCODE_HOST.test(m[2] ?? ''))
      .map(m => Number(m[1])),
  )
  const rootOf = new Map<string, string>()
  for (const f of new Set(windows.flatMap(w => w.folders))) rootOf.set(f, await repoRoot($, f))

  return windowFolderFor(windows, alive, rootOf, await repoRoot($, r.cwd))
}

/** The main checkout's root for a cwd (a worktree's included): where its VS Code window is. */
async function repoRoot($: EngineInterface, cwd: string): Promise<string> {
  const git = await $.process
    .run(['git', '-C', cwd, 'rev-parse', '--path-format=absolute', '--git-common-dir'])
    .catch(() => undefined)
  const common = git?.exitCode === 0 ? git.stdout.trim() : ''

  return common.endsWith('/.git') ? common.slice(0, -'/.git'.length) : cwd
}

/**
 * A session whose repo is open in a VS Code window opens there: the window is
 * raised and the helper focuses the tab already showing the session, else
 * opens one. A repo with no window open gets a new Terminal.app window (never
 * a new VS Code window). Never this session's own terminal. tmux mirrors
 * every client of a session, so a view already showing it keeps working.
 */
async function openSession($: EngineInterface, r: SessionRow): Promise<string> {
  const name = nameOf(r)
  const selfId = await $.session.id()
  if (r.sessionId === selfId) return `${name} is this session.`
  if (!r.tmux) return `${name} runs outside tmux: there is nothing to attach to.`
  const socket = await socketOf($, r)
  if (!socket) return `Could not find ${name}'s tmux server.`
  const attach = attachCommand(socket, r.tmux)
  const nonce = crypto.randomUUID()
  const uri = vscodeUri(socket, r.tmux, nonce)
  if (!attach || !uri) return `Refused: ${name} has a name the opener will not quote.`
  const clients = await $.process
    .run(['tmux', '-L', socket, 'list-clients', '-t', `=${r.tmux}`, '-F', '#{client_tty}'])
    .catch(() => undefined)
  const ttys = (clients?.stdout ?? '').split('\n').filter(Boolean).map(t => t.replace('/dev/', ''))
  const also = ttys.length ? ` (also attached on ${ttys.join(', ')})` : ''

  const folder = await vscodeFolderFor($, r)
  if (folder) {
    // Bring that window forward first (`code <its folder>` raises the window
    // showing it), so the link lands there rather than in whichever was last.
    let isRaised = false
    for (const cli of CODE_CLIS) {
      const raised = await $.process.run([cli, folder]).catch(() => undefined)
      if (raised?.exitCode === 0) {
        isRaised = true
        break
      }
    }
    // The helper honours only a link carrying the token it finds in this file.
    const home = await $.env.get('HOME')
    const isArmed = await $.fs
      .write(`${home}/${VSCODE_NONCE_FILE}`, nonce)
      .then(() => true)
      .catch(() => false)
    if (isRaised && isArmed) {
      await $.clock.sleep(800)
      const sent = await $.process.run(['open', uri]).catch(() => ({ exitCode: 1 }))
      // The helper decides there: a tab of that window already showing the
      // session is focused, else a new one opens.
      if (sent.exitCode === 0) {
        return ttys.length
          ? `Showed ${name} in VS Code (${folder}): its tab is focused if that window has one, else a new tab opens.`
          : `Opened ${name} in a new VS Code terminal in ${folder}.`
      }
    }
  }

  const run = await $.process.run([
    'osascript',
    '-e',
    'tell application "Terminal"',
    '-e',
    `do script "${attach}"`,
    '-e',
    'activate',
    '-e',
    'end tell',
  ])
  if (run.exitCode !== 0) return `Could not open ${name}: ${run.stderr.trim() || `exit ${run.exitCode}`}`

  return `Opened ${name} in a new Terminal window${also}.`
}

async function openFromPane($: EngineInterface, r: SessionRow) {
  $.ui.toast(await openSession($, r).catch(err => `Could not open: ${String(err)}`))
}

// The VS Code helper is offered once: `$.store` keeps the answer.
const HELPER_CHOICE = 'vscodeHelper'
const VSCODE_STORAGE = 'Library/Application Support/Code/User/globalStorage/storage.json'
const HELPER_QUESTION =
  'Install the agent-roster helper into all your VS Code profiles, so open can go straight to a running window?'

/** The names of the VS Code profiles beyond Default, from VS Code's own storage. */
export function profileNames(storage: unknown): string[] {
  const profiles = (storage as { userDataProfiles?: { name?: unknown }[] } | null)?.userDataProfiles
  if (!Array.isArray(profiles)) return []

  // A name starting with a dash would read as a flag to `code --profile`.
  return profiles
    .map(p => p?.name)
    .filter((n): n is string => typeof n === 'string' && n.length > 0 && !n.startsWith('-'))
}

async function helperInstalled($: EngineInterface, home: string): Promise<boolean> {
  const installed = await $.fs.list(`${home}/.vscode/extensions`).catch(() => [])

  return installed.some(e => e.name.startsWith('pip.agent-roster-vscode-'))
}

/** Builds the helper and installs it into Default and every VS Code profile. */
async function installHelper($: EngineInterface): Promise<string> {
  const home = await $.env.get('HOME')
  const storage = await $.fs.read(`${home}/${VSCODE_STORAGE}`).catch(() => undefined)
  let profiles: string[] = []
  try {
    profiles = profileNames(JSON.parse(String(storage)))
  } catch {
    // No VS Code storage yet: Default alone.
  }
  // A Dock-launched host may lack Homebrew on PATH, where `code` lives.
  const path = `/opt/homebrew/bin:/usr/local/bin:${(await $.env.get('PATH')) ?? '/usr/bin:/bin'}`
  const run = await $.process
    .run(['sh', `${$.plugin.root}/vscode/build.sh`, 'install', ...profiles], {
      env: { PATH: path },
      timeoutMs: 180_000,
    })
    .catch((err: unknown) => ({ exitCode: 1, stdout: '', stderr: String(err) }))
  if (run.exitCode !== 0) {
    const why = run.stderr.trim().split('\n').pop() || `exit ${run.exitCode}`
    return `Could not install the VS Code helper: ${why}`
  }
  await $.store.set(HELPER_CHOICE, 'installed')
  const where = ['Default', ...profiles].join(', ')

  return `Installed the VS Code helper into ${where}. Reload open VS Code windows (Developer: Reload Window) so open can find them.`
}

// How long an open helper question keeps other sessions from asking it too.
const ASK_HOLD_MS = 10 * 60_000

/** Asks once, the first time the mod loads with VS Code present and no helper. */
async function offerHelper($: EngineInterface) {
  // 'installed' or 'never' settle it; a number is "Not now" until then.
  const choice = await $.store.get(HELPER_CHOICE)
  if (typeof choice === 'string' || (typeof choice === 'number' && choice > Date.now())) return
  // A -p or SDK run draws nowhere: nobody to ask.
  if ((await $.session.surfaces()).length === 0) return
  const home = (await $.env.get('HOME')) ?? ''
  if (!(await $.fs.exists(`${home}/.vscode`))) return
  if (await helperInstalled($, home)) {
    await $.store.set(HELPER_CHOICE, 'installed')
    return
  }
  // Many sessions start at once: the first to get here claims the question for
  // a while, so the rest stay quiet while it is open. Dismissed, the claim just
  // lapses and a later session asks; "Not now" waits a day.
  await $.store.set(HELPER_CHOICE, Date.now() + ASK_HOLD_MS)
  const answer = await $.ui
    .ask(HELPER_QUESTION, { header: 'VS Code', options: ['Install', 'Not now', 'Never'] })
    .catch(() => undefined)
  if (answer === 'Install') {
    $.ui.toast(await installHelper($), { timeoutMs: 10_000 })
  } else if (answer === 'Not now') {
    await $.store.set(HELPER_CHOICE, Date.now() + 24 * 3600_000)
  } else if (answer === 'Never') {
    await $.store.set(HELPER_CHOICE, 'never')
    $.ui.toast('Not installing the VS Code helper; /roster setup-vscode installs it any time.')
  }
}

const USAGE =
  'Usage: /roster, /roster open <tmux-name|pid>, /roster kill <tmux-name|pid>, or /roster setup-vscode'

const STATUS_COLOR: Record<string, string> = { waiting: 'red', busy: 'green' }

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    // Polling first: a refused command must not take the roster down with it.
    $.clock.every(POLL_MS, () => void refresh($).catch(() => undefined))
    void refresh($).catch(() => undefined)
    // `/agents` is a built-in, so the command is `/roster`.
    await $.command
      .register({
        name: COMMAND,
        description: 'Claude sessions in this config dir, plus tmux startup prompts: tmux name, repo, status, last active',
      })
      .catch(() => undefined)
    // After the session settles, so the question is not the first thing drawn.
    $.clock.after(3000, () => void offerHelper($).catch(() => undefined))

    return next(e)
  })

  // The Claude app over Remote Control relays commands but attaches no drawing
  // surface (it never asks to draw the pane), so from there the reply is the
  // roster itself. That text is a transcript row the model reads too.
  on('command.run', { command: COMMAND }, async ($, e) => {
    await refresh($)
    const args = e.args.trim()
    const failed = (err: unknown) => `Could not ${args.split(' ')[0]}: ${String(err)}`
    if (args === 'setup-vscode') return { text: await installHelper($).catch(failed) }
    if (args) {
      const [, verb, target] = /^(kill|open)\s+(\S+)$/.exec(args) ?? []
      if (!verb || !target) return { text: USAGE }
      const { rows } = await read($, sessions)
      const matches = matchTarget(rows, target)
      if (matches.length === 0) return { text: `No live session named ${target}.` }
      if (matches.length > 1) {
        const pids = matches.map(m => m.pid).join(', ')
        return { text: `${target} is ambiguous; ${verb} by pid: ${pids}` }
      }
      const message =
        verb === 'kill'
          ? await killSession($, matches[0]!).catch(failed)
          : await openSession($, matches[0]!).catch(failed)
      await rescanAfterCurrent($)

      return { text: message }
    }
    if (e.origin.kind === 'bridge') {
      const { rows, checkedAt, warnings } = await read($, sessions)
      return { text: summary(rows, checkedAt, warnings) }
    }
    await $.ui.open({ id: PANE, title: TITLE, focus: true })

    return { text: 'Agents pane opened.' }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const { rows, checkedAt, selfId, error, warnings = [] } = await read($, sessions)
    const pending = await read($, pendingKill)
    const isShowingOlder = await read($, showOlder)
    const tabs = repoTabs(rows)
    // A tab whose last session went away falls back to All.
    const selected = await read($, repoTab)
    const tab = tabs.some(t => t.repo === selected) ? selected : null
    const visible = tab ? rows.filter(r => r.repo === tab) : rows
    const { waiting, busy, recent, older } = grouped(visible, checkedAt)
    const all = grouped(rows, checkedAt)

    // Two presses to kill: the first only arms the row.
    const controls = (r: SessionRow) =>
      r.sessionId === selfId ? (
        <Text dimColor>this</Text>
      ) : pending === r.pid ? (
        <Box flexDirection="row" gap={1}>
          <Button key={`confirm-${r.pid}`} variant="primary" onPress={() => void killFromPane($, r)}>
            confirm kill
          </Button>
          <Button key={`cancel-${r.pid}`} onPress={() => void update($, pendingKill, () => null)}>
            cancel
          </Button>
        </Box>
      ) : (
        <Box flexDirection="row" gap={1}>
          {r.tmux && (
            <Button key={`open-${r.pid}`} onPress={() => void openFromPane($, r)}>
              open
            </Button>
          )}
          {!isStray(r) && (
            <Button key={`kill-${r.pid}`} dimColor onPress={() => void update($, pendingKill, () => r.pid)}>
              kill
            </Button>
          )}
        </Box>
      )

    const where = (r: SessionRow) =>
      [
        nameOf(r),
        r.worktree ? `${r.repo}/${r.worktree}` : r.repo,
        r.branch,
        r.kind === 'bg' ? 'bg' : undefined,
        r.account,
      ]
        .filter(Boolean)
        .join(' · ')

    // A session that needs you or is working: a card, its border the status.
    const card = (r: SessionRow) => (
      <Box
        key={`card-${r.pid}`}
        flexDirection="column"
        borderStyle="round"
        borderColor={STATUS_COLOR[r.status]}
        paddingX={1}
      >
        <Box flexDirection="row" gap={1}>
          <Box flexGrow={1}>
            <Text bold wrap="truncate-end">
              {label(r)}
            </Text>
          </Box>
          <Text dimColor>{ago(r.lastActive, checkedAt)}</Text>
          {controls(r)}
        </Box>
        <Text dimColor wrap="truncate-end">
          {where(r)}
        </Text>
        {r.status === 'waiting' && (
          <Text color="red" bold>
            ? {r.waitingFor ?? 'waiting on you'}
          </Text>
        )}
        {r.note && <Text dimColor>{r.note}</Text>}
        {r.prompt && (
          <Text dimColor italic wrap="truncate-end">
            you{r.promptAt ? ` ${ago(r.promptAt, checkedAt)} ago` : ''}: {r.prompt}
          </Text>
        )}
      </Box>
    )

    // An idle session: one quiet line.
    const line = (r: SessionRow) => (
      <Box key={`line-${r.pid}`} flexDirection="row" gap={1} paddingX={1}>
        <Box flexGrow={1}>
          <Text dimColor wrap="truncate-end">
            {r.status === 'shell' ? '$' : '·'} <Text bold>{label(r)}</Text> {nameOf(r)}
            {r.account ? ` · ${r.account}` : ''}
            {r.note ? ` · ${r.note}` : ''}
          </Text>
        </Box>
        <Text dimColor>{ago(r.lastActive, checkedAt)}</Text>
        {controls(r)}
      </Box>
    )

    const heading = (text: string, count: number, color?: string) => (
      <Box marginTop={1}>
        <Text bold color={color}>
          {text}
        </Text>
        <Text dimColor> {count}</Text>
      </Box>
    )

    const pill = (text: string, color: string, ink = 'black') => (
      <Text backgroundColor={color} color={ink} bold>
        {` ${text} `}
      </Text>
    )

    // Hotkeys 1-9 while the pane holds the keyboard: 1 is All, then the repos in order.
    // A Button's label is one plain string, so the coloured counts sit beside it.
    const tabButton = (repo: string | null, name: string, marks: TabMark[], index: number) => (
      <Box key={`tabbox-${repo ?? '*all'}`} flexDirection="row" columnGap={1} marginRight={1}>
        <Button
          key={`tab-${repo ?? '*all'}`}
          hotkey={index < 9 ? String(index + 1) : undefined}
          variant={tab === repo ? 'primary' : undefined}
          dimColor={tab !== repo}
          onPress={() => void update($, repoTab, () => repo)}
        >
          {name}
        </Button>
        {marks.map(m => (
          <Text color={m.color} bold={m.color !== 'gray'}>
            {m.text}
          </Text>
        ))}
      </Box>
    )
    const allMarks = tabMarks({ waiting: all.waiting.length, busy: all.busy.length, total: rows.length })

    return (
      <Box flexDirection="column">
        <Box flexDirection="row" gap={1}>
          {all.waiting.length > 0 && pill(`? ${all.waiting.length} NEED YOU`, 'red', 'white')}
          {all.busy.length > 0 && pill(`● ${all.busy.length} WORKING`, 'green')}
          <Text dimColor>○ {all.recent.length + all.older.length} idle</Text>
          <Box flexGrow={1} />
          <Text dimColor>updated {ago(checkedAt, Date.now())} ago</Text>
          <Button key="refresh" hotkey="r" dimColor onPress={() => void refreshNow($)}>
            refresh
          </Button>
        </Box>
        {warnings.map(w => (
          <Text key={`warn-${w}`} color="yellow" wrap="truncate-end">
            could not read {w}
          </Text>
        ))}
        {error && (
          <Text color="red" wrap="truncate-end">
            Last scan failed, showing the one before: {error}
          </Text>
        )}
        <Box flexDirection="row" flexWrap="wrap" marginTop={1}>
          {tabButton(null, 'All', allMarks, 0)}
          {tabs.map((t, i) => tabButton(t.repo, t.repo, tabMarks(t), i + 1))}
        </Box>
        {rows.length === 0 && <Text dimColor>No live sessions found.</Text>}
        {waiting.length > 0 && heading('Needs you', waiting.length, 'red')}
        {waiting.map(card)}
        {busy.length > 0 && heading('Working', busy.length, 'green')}
        {busy.map(card)}
        {recent.length + older.length > 0 && heading('Idle', recent.length + older.length)}
        {recent.map(line)}
        {isShowingOlder && older.map(line)}
        {older.length > 0 && (
          <Box paddingX={1}>
            <Button key="older" plain dimColor onPress={() => void update($, showOlder, v => !v)}>
              {isShowingOlder ? 'hide older' : `show ${older.length} idle for over a day`}
            </Button>
          </Box>
        )}
      </Box>
    )
  })
}
