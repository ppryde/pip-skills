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
const repoTab = atom({ plugin: 'agent-roster', key: 'repoTab' } as const, null)

// Waiting first: it needs you. Then busy, then the rest.
const RANK: Record<string, number> = { waiting: 0, busy: 1 }

// Caches only: a reload starts them empty and the next poll refills them.
const transcriptPaths = new Map<string, string | null>()
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
        ...(await gitRepoOf($, row.cwd)),
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

/** A refresh the person asked for: branches re-read now, not when their minute is up. */
async function refreshNow($: EngineInterface) {
  branches.clear()
  await refresh($)
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

// What may be spliced into the shell line and the AppleScript string below.
const SAFE_NAME = /^[\w.-]+$/

/** The shell line that attaches a terminal to one tmux session on one socket. */
export function attachCommand(socket: string, name: string): string | undefined {
  if (!SAFE_NAME.test(socket) || !SAFE_NAME.test(name)) return undefined

  return `tmux -L ${socket} attach -t '=${name}'`
}

/** The link the VS Code helper (`vscode/`) answers with a terminal tab attached to the session. */
export function vscodeUri(socket: string, name: string): string | undefined {
  if (!SAFE_NAME.test(socket) || !SAFE_NAME.test(name)) return undefined

  return `vscode://pip.agent-roster-vscode/attach?socket=${socket}&name=${name}`
}

// `code`, wherever Homebrew or the app put it.
const CODE_CLIS = ['/opt/homebrew/bin/code', '/usr/local/bin/code']
// Where the helper has each open VS Code window name its folders.
const VSCODE_WINDOWS_DIR = '.cache/agent-roster/vscode-windows'

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
  // A window that crashed leaves its file: only live extension hosts count.
  const ps = await $.process.run(['ps', '-o', 'pid=', '-p', windows.map(w => w.pid).join(',')])
  const alive = new Set(ps.stdout.split('\n').map(line => Number(line.trim())))
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
  const uri = vscodeUri(socket, r.tmux)
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
    if (isRaised) {
      await $.clock.sleep(800)
      const sent = await $.process.run(['open', uri])
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

// The VS Code helper is offered once per account: `$.store` keeps the answer.
const HELPER_CHOICE = 'vscodeHelper'
const VSCODE_STORAGE = 'Library/Application Support/Code/User/globalStorage/storage.json'
const HELPER_QUESTION =
  'Install the agent-roster helper into all your VS Code profiles, so open can go straight to a running window?'

/** The names of the VS Code profiles beyond Default, from VS Code's own storage. */
export function profileNames(storage: unknown): string[] {
  const profiles = (storage as { userDataProfiles?: { name?: unknown }[] } | null)?.userDataProfiles
  if (!Array.isArray(profiles)) return []

  return profiles.map(p => p?.name).filter((n): n is string => typeof n === 'string' && n.length > 0)
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

/** Asks once, the first time the mod loads with VS Code present and no helper. */
async function offerHelper($: EngineInterface) {
  if (await $.store.get(HELPER_CHOICE)) return
  const home = (await $.env.get('HOME')) ?? ''
  if (!(await $.fs.exists(`${home}/.vscode`))) return
  if (await helperInstalled($, home)) {
    await $.store.set(HELPER_CHOICE, 'installed')
    return
  }
  // Rejects when dismissed or with nobody to ask (-p): ask again next session.
  const answer = await $.ui
    .ask(HELPER_QUESTION, { header: 'VS Code', options: ['Install', 'Not now', 'Never'] })
    .catch(() => undefined)
  if (answer === 'Install') {
    $.ui.toast(await installHelper($), { timeoutMs: 10_000 })
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
        description: 'Every Claude session on this machine: tmux name, repo, status, last active',
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
    if (args === 'setup-vscode') return { text: await installHelper($) }
    if (args) {
      const [, verb, target] = /^(kill|open)\s+(\S+)$/.exec(args) ?? []
      if (!verb || !target) return { text: USAGE }
      const { rows } = await read($, sessions)
      const matches = matchTarget(rows, target)
      if (matches.length === 0) return { text: `No live session named ${target}.` }
      if (matches.length > 1) {
        const pids = matches.map(m => `${m.pid} (${m.account})`).join(', ')
        return { text: `${target} is ambiguous; ${verb} by pid: ${pids}` }
      }
      const message =
        verb === 'kill' ? await killSession($, matches[0]!) : await openSession($, matches[0]!)
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
          <Button key={`kill-${r.pid}`} dimColor onPress={() => void update($, pendingKill, () => r.pid)}>
            kill
          </Button>
        </Box>
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
        {r.status === 'waiting' && (
          <Text color="red" bold>
            ? {r.waitingFor ?? 'waiting on you'}
          </Text>
        )}
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
