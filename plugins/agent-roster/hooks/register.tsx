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

// Each live Claude process writes <config dir>/sessions/<pid>.json; one config dir per account.
const ACCOUNTS = [
  { account: 'personal', dir: '.claude-personal' },
  { account: 'work', dir: '.claude' },
]

const sessions = atom({ plugin: 'agent-roster', key: 'sessions' } as const, {
  rows: [],
  checkedAt: 0,
})
const pendingKill = atom({ plugin: 'agent-roster', key: 'pendingKill' } as const, null)
const showOlder = atom({ plugin: 'agent-roster', key: 'showOlder' } as const, false)

// Waiting first: it needs you. Then busy, then the rest.
const RANK: Record<string, number> = { waiting: 0, busy: 1 }

// Caches only: a reload starts them empty and the next poll refills them.
const transcriptPaths = new Map<string, string | null>()
const facts = new Map<string, { mtimeMs: number; facts: TranscriptFacts }>()
const branches = new Map<string, { at: number; branch?: string }>()

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

export function toRow(raw: unknown, account: string): SessionRow | undefined {
  if (typeof raw !== 'object' || raw === null) return undefined
  const d = raw as Record<string, unknown>
  if (typeof d.pid !== 'number' || typeof d.cwd !== 'string') return undefined
  const tmux = typeof d.tmux === 'string' ? d.tmux.split(':')[0] : undefined

  return {
    pid: d.pid,
    sessionId: String(d.sessionId ?? ''),
    account,
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

export function headline(rows: SessionRow[]): string {
  const waiting = rows.filter(r => r.status === 'waiting').length
  const busy = rows.filter(r => r.status === 'busy').length

  return `${waiting} need you · ${busy} working · ${rows.length - waiting - busy} idle`
}

const label = (r: SessionRow) => r.title ?? (r.worktree ? `${r.repo}/${r.worktree}` : r.repo)
const nameOf = (r: SessionRow) => r.tmux ?? `pid ${r.pid}`

/** The roster as plain text for Remote Control: sections, one or two lines a session. */
export function summary(rows: SessionRow[], now: number): string {
  const { waiting, busy, recent, older } = grouped(rows, now)
  const lines = [headline(rows)]
  let budget = SUMMARY_ROWS
  const section = (heading: string, list: SessionRow[]) => {
    if (list.length === 0 || budget <= 0) return
    lines.push('', heading)
    for (const r of list.slice(0, budget)) {
      const why = r.status === 'waiting' && r.waitingFor ? ` · ${r.waitingFor}` : ''
      const work = r.account === 'work' ? ' · work' : ''
      lines.push(`• ${label(r)} — ${nameOf(r)} · ${r.repo} · ${ago(r.lastActive, now)}${why}${work}`)
      if (r.prompt) lines.push(`   you ${ago(r.promptAt ?? 0, now)}: ${r.prompt}`)
    }
    budget -= list.length
  }
  section('NEEDS YOU', waiting)
  section('WORKING', busy)
  section('IDLE, LAST 24H', recent)
  if (older.length) lines.push('', `+ ${older.length} idle for over a day`)

  return lines.join('\n')
}

async function transcriptOf($: EngineInterface, configDir: string, row: SessionRow) {
  const known = transcriptPaths.get(row.sessionId)
  if (known !== undefined) return known ?? undefined
  const guess = `${configDir}/projects/${projectSlug(row.cwd)}/${row.sessionId}.jsonl`
  let path: string | undefined = (await $.fs.exists(guess)) ? guess : undefined
  if (!path) {
    // The session moved since launch (into a worktree, say): its transcript stays where it began.
    const found = await $.process
      .run(['find', `${configDir}/projects`, '-maxdepth', '2', '-name', `${row.sessionId}.jsonl`])
      .catch(() => undefined)
    path = found?.stdout.split('\n')[0]?.trim() || undefined
  }
  transcriptPaths.set(row.sessionId, path ?? null)

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

async function scan($: EngineInterface): Promise<SessionRow[]> {
  const home = await $.env.get('HOME')
  const found: { row: SessionRow; configDir: string }[] = []
  for (const { account, dir } of ACCOUNTS) {
    const configDir = `${home}/${dir}`
    const entries = await $.fs.list(`${configDir}/sessions`).catch(() => [])
    for (const entry of entries) {
      if (!entry.name.endsWith('.json')) continue
      const text = await $.fs.read(`${configDir}/sessions/${entry.name}`).catch(() => undefined)
      if (typeof text !== 'string') continue
      try {
        const row = toRow(JSON.parse(text), account)
        if (row) found.push({ row, configDir })
      } catch {
        // A file caught mid-write; the next poll reads it whole.
      }
    }
  }
  if (found.length === 0) return []

  // The registry outlives crashed processes: keep only pids still running.
  const ps = await $.process.run(['ps', '-o', 'pid=', '-p', found.map(f => f.row.pid).join(',')])
  const alive = new Set(ps.stdout.split('\n').map(line => Number(line.trim())))

  return Promise.all(
    found
      .filter(f => alive.has(f.row.pid))
      .map(async ({ row, configDir }) => ({
        ...row,
        branch: await branchOf($, row.cwd),
        ...(await factsOf($, configDir, row)),
      })),
  )
}

async function refresh($: EngineInterface) {
  const rows = sorted(await scan($))
  const selfId = await $.session.id()
  await update($, sessions, () => ({ rows, checkedAt: Date.now(), selfId }))
  const waiting = rows.filter(r => r.status === 'waiting').length
  $.ui.status(waiting ? `agents: ${waiting} waiting` : undefined)
}

/** The sessions a `/roster kill` argument names: a tmux name or a pid. */
export function matchTarget(rows: SessionRow[], target: string): SessionRow[] {
  return rows.filter(r => r.tmux === target || String(r.pid) === target)
}

// The wrapper's sockets first; any other server under the tmux dir after.
const KNOWN_SOCKETS = ['claude-personal', 'claude', 'default']

/** The tmux socket whose session of this name has the session's own pid in a pane. */
async function socketOf($: EngineInterface, r: SessionRow): Promise<string | undefined> {
  const uid = (await $.process.run(['id', '-u'])).stdout.trim()
  const listed = await $.fs.list(`/tmp/tmux-${uid}`).catch(() => [])
  const sockets = [...new Set([...KNOWN_SOCKETS, ...listed.map(s => s.name)])]
  for (const socket of sockets) {
    const panes = await $.process
      .run(['tmux', '-L', socket, 'list-panes', '-s', '-t', `=${r.tmux}`, '-F', '#{pane_pid}'])
      .catch(() => undefined)
    // A name alone is not enough: both accounts' sockets can hold the same one.
    if (panes?.exitCode === 0 && panes.stdout.split('\n').includes(String(r.pid))) return socket
  }

  return undefined
}

/**
 * Ends a session: its whole tmux session when it has one (so no orphaned
 * shell pane is left), else SIGTERM to its pid. Never the session it runs in.
 */
async function killSession($: EngineInterface, r: SessionRow): Promise<string> {
  const name = nameOf(r)
  if (r.sessionId === (await $.session.id())) return `Refused: ${name} is this session.`
  const socket = r.tmux ? await socketOf($, r) : undefined
  const run =
    r.tmux && socket
      ? await $.process.run(['tmux', '-L', socket, 'kill-session', '-t', `=${r.tmux}`])
      : await $.process.run(['kill', String(r.pid)])
  if (run.exitCode !== 0) return `Could not kill ${name}: ${run.stderr.trim() || `exit ${run.exitCode}`}`

  return socket ? `Killed tmux session ${name} (socket ${socket}).` : `Sent SIGTERM to ${name}.`
}

async function killFromPane($: EngineInterface, r: SessionRow) {
  const message = await killSession($, r).catch(err => `Could not kill: ${String(err)}`)
  await update($, pendingKill, () => null)
  $.ui.toast(message)
  await refresh($)
}

const USAGE = 'Usage: /roster, or /roster kill <tmux-name|pid>'

const STATUS_COLOR: Record<string, string> = { waiting: 'yellow', busy: 'green' }

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    // Polling first: a refused command must not take the roster down with it.
    $.clock.every(POLL_MS, () => void refresh($).catch(() => undefined))
    void refresh($).catch(() => undefined)
    // `/agents` is a built-in, so the command is `/roster`.
    await $.command
      .register({
        name: COMMAND,
        description: 'Every Claude session on this machine: tmux name, repo, status, last active',
      })
      .catch(() => undefined)

    return next(e)
  })

  // The Claude app over Remote Control relays commands but attaches no drawing
  // surface (it never asks to draw the pane), so from there the reply is the
  // roster itself. That text is a transcript row the model reads too.
  on('command.run', { command: COMMAND }, async ($, e) => {
    await refresh($)
    const args = e.args.trim()
    if (args) {
      const target = /^kill\s+(\S+)$/.exec(args)?.[1]
      if (!target) return { text: USAGE }
      const { rows } = await read($, sessions)
      const matches = matchTarget(rows, target)
      if (matches.length === 0) return { text: `No live session named ${target}.` }
      if (matches.length > 1) {
        const pids = matches.map(m => `${m.pid} (${m.account})`).join(', ')
        return { text: `${target} is ambiguous; kill by pid: ${pids}` }
      }
      const message = await killSession($, matches[0]!)
      await refresh($)

      return { text: message }
    }
    if (e.origin.kind === 'bridge') {
      const { rows, checkedAt } = await read($, sessions)
      return { text: summary(rows, checkedAt) }
    }
    await $.ui.open({ id: PANE, title: TITLE, focus: true })

    return { text: 'Agents pane opened.' }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const { rows, checkedAt, selfId } = await read($, sessions)
    const pending = await read($, pendingKill)
    const isShowingOlder = await read($, showOlder)
    const { waiting, busy, recent, older } = grouped(rows, checkedAt)

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
        <Button key={`kill-${r.pid}`} dimColor onPress={() => void update($, pendingKill, () => r.pid)}>
          kill
        </Button>
      )

    const where = (r: SessionRow) =>
      [
        nameOf(r),
        r.worktree ? `${r.repo}/${r.worktree}` : r.repo,
        r.branch,
        r.account === 'work' ? 'work' : undefined,
        r.kind === 'bg' ? 'bg' : undefined,
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
        {r.status === 'waiting' && r.waitingFor && <Text color="yellow">▸ {r.waitingFor}</Text>}
        {r.prompt && (
          <Text dimColor italic wrap="truncate-end">
            you {ago(r.promptAt ?? 0, checkedAt)} ago: {r.prompt}
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
            {r.account === 'work' ? ' · work' : ''}
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

    const pill = (text: string, color: string) => (
      <Text backgroundColor={color} color="black" bold>
        {` ${text} `}
      </Text>
    )

    return (
      <Box flexDirection="column">
        <Box flexDirection="row" gap={1}>
          {waiting.length > 0 && pill(`${waiting.length} NEED YOU`, 'yellow')}
          {busy.length > 0 && pill(`${busy.length} WORKING`, 'green')}
          <Text dimColor>{recent.length + older.length} idle</Text>
        </Box>
        {rows.length === 0 && <Text dimColor>No live sessions found.</Text>}
        {waiting.length > 0 && heading('Needs you', waiting.length, 'yellow')}
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
