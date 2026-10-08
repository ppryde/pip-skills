import { expect, test } from 'claude-code/testing'

import {
  ago,
  attachCommand,
  claudePidsIn,
  grouped,
  headline,
  matchTarget,
  mayKillTmuxSession,
  profileNames,
  projectSlug,
  repoFromGit,
  repoOf,
  repoTabs,
  sorted,
  strayRows,
  summary,
  tabMarks,
  toRow,
  transcriptFacts,
  vscodeUri,
  windowFolderFor,
} from '../../plugins/agent-roster/hooks/register'

const DAY = 86_400_000
const base = { sessionId: '', account: 'personal', cwd: '/r', repo: 'r', kind: 'interactive' }

test('the headline counts who needs you, who works and who idles', async () => {
  const rows = [
    { ...base, pid: 1, status: 'waiting', lastActive: 0 },
    { ...base, pid: 2, status: 'busy', lastActive: 0 },
    { ...base, pid: 3, status: 'shell', lastActive: 0 },
  ]

  expect(headline(rows)).toBe('1 need you · 1 working · 1 idle')
})

test('one tab per repo, those needing you first, each labelled with its marks', async () => {
  const tabs = repoTabs([
    { ...base, pid: 1, repo: 'warehouse', status: 'idle', lastActive: 900 },
    { ...base, pid: 2, repo: 'pip-skills', status: 'busy', lastActive: 10 },
    { ...base, pid: 3, repo: 'ledger-poc', status: 'waiting', lastActive: 5 },
    { ...base, pid: 4, repo: 'pip-skills', status: 'waiting', lastActive: 20 },
    { ...base, pid: 5, repo: 'agents.md', status: 'idle', lastActive: 50 },
  ])

  expect(tabs.map(t => t.repo)).toEqual(['pip-skills', 'ledger-poc', 'warehouse', 'agents.md'])
  expect(tabs.map(t => tabMarks(t).map(m => `${m.color}:${m.text}`))).toEqual([
    ['red:?1', 'green:●1'],
    ['red:?1'],
    ['gray:○1'],
    ['gray:○1'],
  ])
})

test('a /rename title beats the AI one; the prompt is the last one a person typed', async () => {
  const lines = [
    '{"type":"ai-title","aiTitle":"Old title"}',
    '{"type":"user","origin":{"kind":"human"},"timestamp":"2026-10-04T10:00:00.000Z","message":{"content":"fix the\\n  flaky   test"}}',
    '{"type":"ai-title","aiTitle":"Flaky test hunt"}',
    '{"type":"custom-title","customTitle":"My rename"}',
    '{"type":"user","origin":{"kind":"human"},"message":{"content":"<command-name>/roster</command-name>"}}',
    '{"type":"queue-operation","origin":{"kind":"human"}}',
    'not json',
  ].join('\n')

  expect(transcriptFacts(lines)).toEqual({
    title: 'My rename',
    prompt: 'fix the flaky test',
    promptAt: Date.parse('2026-10-04T10:00:00.000Z'),
  })
  expect(transcriptFacts('{"type":"ai-title","aiTitle":"Only AI"}').title).toBe('Only AI')
  expect(transcriptFacts('')).toEqual({ title: undefined, prompt: undefined, promptAt: undefined })
})

test('idle sessions split at a day; waiting and busy never fold', async () => {
  const now = 10 * DAY
  const groups = grouped(
    [
      { ...base, pid: 1, status: 'waiting', lastActive: 0 },
      { ...base, pid: 2, status: 'idle', lastActive: now - 3600_000 },
      { ...base, pid: 3, status: 'idle', lastActive: now - 2 * DAY },
      { ...base, pid: 4, status: 'busy', lastActive: 0 },
    ],
    now,
  )

  expect(groups.waiting.map(r => r.pid)).toEqual([1])
  expect(groups.busy.map(r => r.pid)).toEqual([4])
  expect(groups.recent.map(r => r.pid)).toEqual([2])
  expect(groups.older.map(r => r.pid)).toEqual([3])
})

test('summarises the roster for the phone in sections, your prompt with its age', async () => {
  const now = 10 * DAY
  const text = summary(
    [
      {
        ...base,
        pid: 1,
        tmux: 'cc-ledger-poc-2',
        repo: 'ledger-poc',
        status: 'waiting',
        waitingFor: 'input needed',
        lastActive: now - 120_000,
        title: 'Demo cards',
        prompt: 'add demo cards',
        promptAt: now - 2 * DAY,
      },
      { ...base, pid: 2, account: 'work', repo: 'warehouse', status: 'idle', lastActive: now - 3 * DAY },
    ],
    now,
  )

  expect(text).toBe(
    [
      '1 need you · 0 working · 1 idle',
      '',
      'NEEDS YOU',
      '• Demo cards — cc-ledger-poc-2 · ledger-poc · 2m · input needed',
      '   you 2d: add demo cards',
      '',
      '+ 1 idle for over a day',
    ].join('\n'),
  )
})

test('reads a registry entry into a row: tmux name, repo, worktree, why it waits', async () => {
  const row = toRow(
    {
      pid: 51438,
      sessionId: 's1',
      cwd: '/Users/me/repos/ledger-poc/.claude/worktrees/w2-demoui',
      tmux: 'cc-ledger-poc-1:@0.%0',
      status: 'waiting',
      waitingFor: 'input needed',
      kind: 'interactive',
      updatedAt: 1000,
    },
    'personal',
  )

  expect(row).toEqual({
    pid: 51438,
    sessionId: 's1',
    account: 'personal',
    tmux: 'cc-ledger-poc-1',
    cwd: '/Users/me/repos/ledger-poc/.claude/worktrees/w2-demoui',
    repo: 'ledger-poc',
    worktree: 'w2-demoui',
    status: 'waiting',
    waitingFor: 'input needed',
    kind: 'interactive',
    lastActive: 1000,
  })
  expect(repoOf('/Users/me/repos/pip-skills')).toEqual({ repo: 'pip-skills' })
  expect(toRow({ cwd: '/x' }, 'work')).toBe(undefined)
})

test('files transcripts under the cwd with every non-alphanumeric as a dash', async () => {
  expect(projectSlug('/Users/philip.pryde/repos/pip-skills')).toBe(
    '-Users-philip-pryde-repos-pip-skills',
  )
})

test('waiting sessions first, then busy, then the rest by last active', async () => {
  const rows = sorted([
    { ...base, pid: 1, status: 'idle', lastActive: 50 },
    { ...base, pid: 2, status: 'busy', lastActive: 10 },
    { ...base, pid: 3, status: 'idle', lastActive: 90 },
    { ...base, pid: 4, status: 'waiting', lastActive: 5 },
  ])

  expect(rows.map(r => r.pid)).toEqual([4, 2, 3, 1])
  expect(ago(0, 90_000)).toBe('2m')
  expect(ago(0, 3 * DAY)).toBe('3d')
})

test('a kill target is a tmux name or a pid, and a name on both accounts is two matches', async () => {
  const rows = [
    { ...base, pid: 23156, status: 'idle', lastActive: 0, tmux: 'cc-take-home-tasks-2' },
    { ...base, pid: 83438, status: 'idle', lastActive: 0, account: 'work', tmux: 'cc-take-home-tasks-2' },
    { ...base, pid: 75378, status: 'idle', lastActive: 0 },
  ]

  expect(matchTarget(rows, 'cc-take-home-tasks-2').map(r => r.pid)).toEqual([23156, 83438])
  expect(matchTarget(rows, '83438').map(r => r.pid)).toEqual([83438])
  expect(matchTarget(rows, '75378').map(r => r.pid)).toEqual([75378])
  expect(matchTarget(rows, 'cc-take-home')).toEqual([])
})

test('the opener attaches by exact name on the found socket, and refuses unquotable names', async () => {
  expect(attachCommand('claude-personal', 'cc-pip-skills-10')).toBe(
    "tmux -L claude-personal attach -t '=cc-pip-skills-10'",
  )
  expect(attachCommand('claude', "x'; rm -rf ~")).toBe(undefined)
  expect(attachCommand('claude', 'a"b')).toBe(undefined)
})

test('the VS Code link carries socket, exact name and the one-time token, and refuses what it cannot pass', async () => {
  const nonce = '0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0'
  expect(vscodeUri('claude-personal', 'cc-pip-skills-9', nonce)).toBe(
    `vscode://pip.agent-roster-vscode/attach?socket=claude-personal&name=cc-pip-skills-9&nonce=${nonce}`,
  )
  expect(vscodeUri('claude', 'a&b=c', nonce)).toBe(undefined)
  expect(vscodeUri('claude', 'ok', 'short')).toBe(undefined)
  expect(vscodeUri('claude', '..', nonce)).toBe(undefined)
  expect(attachCommand('claude', '-x')).toBe(undefined)
})

test("a sibling worktree belongs to its main checkout's repo, by what git says", async () => {
  const common = '/Users/me/repos/pip-skills/.git'
  expect(repoFromGit('/Users/me/repos/pip-skills-agent-roster', '/Users/me/repos/pip-skills-agent-roster', common)).toEqual({
    repo: 'pip-skills',
    worktree: 'pip-skills-agent-roster',
  })
  expect(repoFromGit('/Users/me/repos/pip-skills/src', '/Users/me/repos/pip-skills', common)).toEqual({
    repo: 'pip-skills',
  })
  // Not a git folder: fall back to the path.
  expect(repoFromGit('/tmp/scratch-1', '', '')).toEqual({ repo: 'scratch-1' })
})

test('open goes to a live VS Code window showing the repo, a worktree or subfolder counting as the repo', async () => {
  const windows = [
    { pid: 10, folders: ['/r/pip-skills'] },
    { pid: 20, folders: ['/r/pip-skills-agent-roster'] },
    { pid: 30, folders: ['/r/warehouse'] },
  ]
  const rootOf = new Map([
    ['/r/pip-skills', '/r/pip-skills'],
    ['/r/pip-skills-agent-roster', '/r/pip-skills'],
    ['/r/warehouse', '/r/warehouse'],
  ])

  expect(windowFolderFor(windows, new Set([10, 20, 30]), rootOf, '/r/pip-skills')).toBe('/r/pip-skills')
  // The main checkout's window is dead (a crash left its file): the worktree's window serves.
  expect(windowFolderFor(windows, new Set([20, 30]), rootOf, '/r/pip-skills')).toBe('/r/pip-skills-agent-roster')
  // No window shows the repo: undefined, and the caller opens Terminal instead.
  expect(windowFolderFor(windows, new Set([10, 20, 30]), rootOf, '/r/ledger-poc')).toBe(undefined)
})

test("the helper installs into every VS Code profile VS Code's storage names", async () => {
  expect(
    profileNames({ userDataProfiles: [{ name: 'Personal', location: '-292c' }, { name: 'Agents' }, { location: 'x' }] }),
  ).toEqual(['Personal', 'Agents'])
  expect(profileNames({})).toEqual([])
  expect(profileNames(null)).toEqual([])
})

test('a pane running Claude with no registry entry shows as waiting at a startup prompt', async () => {
  const panes = [
    'cc-home-1\t50166\t2.1.289\t/Users/me\t1791148516',
    'cc-pip-skills-9\t48701\t2.1.287\t/Users/me/repos/pip-skills\t1791148000',
    '11\t90605\tzsh\t/Users/me/repos/pip-skills\t1791148000',
  ].join('\n')
  const rows = strayRows(panes, 'claude-personal', { pids: new Set([48701]), tmuxNames: new Set() })

  expect(rows.map(r => [r.tmux, r.pid, r.status, r.account, r.repo, r.lastActive])).toEqual([
    ['cc-home-1', 50166, 'waiting', 'personal', 'me', 1791148516000],
  ])
  expect(rows[0]?.waitingFor).toContain('startup prompt')
})

test('a registry pid counts only while it is still Claude, and never 0 or 1', async () => {
  const ps = [
    '    1 /sbin/launchd',
    '52936 /Users/me/.local/bin/claude',
    '48701 /Users/me/.local/share/claude/versions/2.1.289',
    '61234 /usr/bin/vim',
    '',
  ].join('\n')

  expect([...claudePidsIn(ps)].sort()).toEqual([48701, 52936])
  expect(toRow({ pid: 0, cwd: '/r' }, 'personal')).toBe(undefined)
  expect(toRow({ pid: 1.5, cwd: '/r' }, 'personal')).toBe(undefined)
})

test('kill ends a whole tmux session only when it cannot hold this one', async () => {
  const target = { tmux: 'cc-a-1', account: 'personal' }
  const self = { pid: 333, tmux: 'cc-me-1', account: 'personal' }

  expect(mayKillTmuxSession(target, [111, 222], self)).toBe(true)
  // This session's Claude sits in one of the target's panes.
  expect(mayKillTmuxSession(target, [111, 333], self)).toBe(false)
  // A shell above Claude hides the pid, but the tmux name still matches.
  expect(mayKillTmuxSession(target, [999], { ...self, tmux: 'cc-a-1' })).toBe(false)
  // The same name on the other account's socket is a different session.
  expect(mayKillTmuxSession(target, [999], { ...self, tmux: 'cc-a-1', account: 'work' })).toBe(true)
  // This session unknown: never a whole tmux session.
  expect(mayKillTmuxSession(target, [111], undefined)).toBe(false)
})

test('a registered session is not listed again as a stray, by pid or by tmux name', async () => {
  const panes = 'cc-pip-skills-9\t90001\t2.1.289\t/Users/me/repos/pip-skills\t1791148000'
  expect(strayRows(panes, 'claude-personal', { pids: new Set(), tmuxNames: new Set(['personal:cc-pip-skills-9']) })).toEqual([])
  expect(strayRows(panes, 'claude', { pids: new Set(), tmuxNames: new Set(['personal:cc-pip-skills-9']) })).toHaveLength(1)
  // On a socket that maps to no account, a registered session of that name on any account counts.
  expect(strayRows(panes, 'default', { pids: new Set(), tmuxNames: new Set(['work:cc-pip-skills-9']) })).toEqual([])
})

test('profile names that would read as flags are left out', async () => {
  expect(profileNames({ userDataProfiles: [{ name: '--help' }, { name: 'Work' }] })).toEqual(['Work'])
})
