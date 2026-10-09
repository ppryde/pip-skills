import { expect, test } from 'claude-code/testing'

import {
  ago,
  attachCommand,
  claudePidsIn,
  configDirTag,
  newestPerPid,
  grouped,
  headline,
  matchTarget,
  mayKillTmuxSession,
  profileNames,
  projectSlug,
  repoFromGit,
  repoOf,
  repoTabs,
  resolveConfigDirs,
  sorted,
  strayRows,
  agentsViewPidsIn,
  otherClaudeDirs,
  summary,
  tabMarks,
  toRow,
  isStray,
  transcriptFacts,
  vscodeUri,
  windowFolderFor,
} from '../plugin/hooks/register'

const DAY = 86_400_000
const base = { sessionId: '', cwd: '/r', repo: 'r', kind: 'interactive' }

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
      { ...base, pid: 2, repo: 'warehouse', status: 'idle', lastActive: now - 3 * DAY },
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
  )

  expect(row).toEqual({
    pid: 51438,
    sessionId: 's1',
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
  expect(toRow({ cwd: '/x' })).toBe(undefined)
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

test('a kill target is a tmux name or a pid, and a name on two tmux servers is two matches', async () => {
  const rows = [
    { ...base, pid: 23156, status: 'idle', lastActive: 0, tmux: 'cc-take-home-tasks-2' },
    { ...base, pid: 83438, status: 'idle', lastActive: 0, tmux: 'cc-take-home-tasks-2' },
    { ...base, pid: 75378, status: 'idle', lastActive: 0 },
  ]

  expect(matchTarget(rows, 'cc-take-home-tasks-2').map(r => r.pid)).toEqual([23156, 83438])
  expect(matchTarget(rows, '83438').map(r => r.pid)).toEqual([83438])
  expect(matchTarget(rows, '75378').map(r => r.pid)).toEqual([75378])
  expect(matchTarget(rows, 'cc-take-home')).toEqual([])
})

test('the opener attaches by exact name on the found socket, and refuses unquotable names', async () => {
  expect(attachCommand('default', 'cc-pip-skills-10')).toBe(
    "tmux -L default attach -t '=cc-pip-skills-10'",
  )
  expect(attachCommand('claude', "x'; rm -rf ~")).toBe(undefined)
  expect(attachCommand('claude', 'a"b')).toBe(undefined)
})

test('the VS Code link carries socket, exact name and the one-time token, and refuses what it cannot pass', async () => {
  const nonce = '0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0'
  expect(vscodeUri('default', 'cc-pip-skills-9', nonce)).toBe(
    `vscode://pip.agent-roster-vscode/attach?socket=default&name=cc-pip-skills-9&nonce=${nonce}`,
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
  const rows = strayRows(panes, { pids: new Set([48701]), tmuxNames: new Set() })

  expect(rows.map(r => [r.tmux, r.pid, r.status, r.repo, r.lastActive])).toEqual([
    ['cc-home-1', 50166, 'waiting', 'me', 1791148516000],
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
  expect(toRow({ pid: 0, cwd: '/r' })).toBe(undefined)
  expect(toRow({ pid: 1.5, cwd: '/r' })).toBe(undefined)
})

test('kill ends a whole tmux session only when it cannot hold this one', async () => {
  const target = { tmux: 'cc-a-1' }
  const self = { pid: 333, tmux: 'cc-me-1' }

  expect(mayKillTmuxSession(target, [111, 222], self)).toBe(true)
  // This session's Claude sits in one of the target's panes.
  expect(mayKillTmuxSession(target, [111, 333], self)).toBe(false)
  // A shell above Claude hides the pid, but the tmux name still matches.
  expect(mayKillTmuxSession(target, [999], { ...self, tmux: 'cc-a-1' })).toBe(false)
  // This session unknown: never a whole tmux session.
  expect(mayKillTmuxSession(target, [111], undefined)).toBe(false)
})

test('a registered session is not listed again as a stray, by pid or by tmux name', async () => {
  const panes = 'cc-pip-skills-9\t90001\t2.1.289\t/Users/me/repos/pip-skills\t1791148000'
  expect(strayRows(panes, { pids: new Set([90001]), tmuxNames: new Set() })).toEqual([])
  expect(strayRows(panes, { pids: new Set(), tmuxNames: new Set(['cc-pip-skills-9']) })).toEqual([])
  expect(strayRows(panes, { pids: new Set(), tmuxNames: new Set(['cc-other-1']) })).toHaveLength(1)
})

test('profile names that would read as flags are left out', async () => {
  expect(profileNames({ userDataProfiles: [{ name: '--help' }, { name: 'Beta' }] })).toEqual(['Beta'])
})

test('a config dir is tagged by its name: .claude-X is X, else the dot goes', async () => {
  expect(configDirTag('/home/.claude-personal')).toBe('personal')
  expect(configDirTag('/home/.claude')).toBe('claude')
  expect(configDirTag('/srv/accounts/work/')).toBe('work')
})

test('unset ROSTER_CONFIG_DIRS is the session\'s own dir alone, untagged', async () => {
  expect(resolveConfigDirs(undefined, '/home', '/home/.claude')).toEqual([{ dir: '/home/.claude' }])
  expect(resolveConfigDirs('  ', '/home', '/home/.claude')).toEqual([{ dir: '/home/.claude' }])
})

test('the list expands ~, dedupes by resolved path and leaves the own dir untagged', async () => {
  expect(
    resolveConfigDirs('~/.claude:~/.claude-personal:/home/.claude-personal/:/home/./.claude', '/home', '/home/.claude'),
  ).toEqual([{ dir: '/home/.claude' }, { dir: '/home/.claude-personal', tag: 'personal' }])
})

test('the list splits on ":" unless an entry starts with a drive letter, then on ";"', async () => {
  expect(resolveConfigDirs('/a/.claude:/b/.claude-x', '/h', '/a/.claude')).toEqual([
    { dir: '/a/.claude' },
    { dir: '/b/.claude-x', tag: 'x' },
  ])
  expect(resolveConfigDirs('C:\\u\\.claude;C:\\u\\.claude-work', 'C:\\u', 'C:\\u\\.claude')).toEqual([
    { dir: 'C:\\u\\.claude' },
    { dir: 'C:\\u\\.claude-work', tag: 'work' },
  ])
})

test('a row from another account carries its tag in the Remote Control text', async () => {
  const text = summary(
    [
      { ...base, pid: 1, repo: 'warehouse', status: 'busy', lastActive: 0, account: 'personal' },
      { ...base, pid: 2, repo: 'ledger', status: 'busy', lastActive: 0 },
    ],
    60_000,
  )

  expect(text).toContain('• warehouse — pid 1 · warehouse · 1m · personal')
  expect(text.endsWith('• ledger — pid 2 · ledger · 1m')).toBe(true)
})

test('a list that omits the own dir still reads it first, untagged', async () => {
  expect(resolveConfigDirs('/b/.claude-x', '/h', '/h/.claude')).toEqual([
    { dir: '/h/.claude' },
    { dir: '/b/.claude-x', tag: 'x' },
  ])
})

test('~\\ expands to home too, and a Windows list dedupes without regard to case', async () => {
  expect(resolveConfigDirs('~\\.claude-work;c:\\U\\.CLAUDE-WORK', 'C:\\U', 'C:\\U\\.claude')).toEqual([
    { dir: 'C:\\U\\.claude' },
    { dir: 'C:\\U\\.claude-work', tag: 'work' },
  ])
  expect(resolveConfigDirs('C:\\u\\.CLAUDE', 'C:\\u', 'C:\\u\\.claude')).toEqual([{ dir: 'C:\\u\\.claude' }])
})

test('the Remote Control text warns of dirs that could not be read', async () => {
  const text = summary([{ ...base, pid: 1, status: 'busy', lastActive: 0 }], 60_000, ['personal: EACCES'])

  expect(text.split('\n').at(-1)).toBe('! could not read personal: EACCES')
})

test('relative dirs fold "." and ".." too, so two spellings are one dir', async () => {
  expect(resolveConfigDirs('foo/../bar:bar/:./bar', '/h', '/h/.claude')).toEqual([
    { dir: '/h/.claude' },
    { dir: 'bar', tag: 'bar' },
  ])
})

test('a UNC entry switches the split to ";" like a drive letter', async () => {
  expect(resolveConfigDirs('\\\\srv\\a\\.claude-x;\\\\srv\\b\\.claude-y', '/h', '/h/.claude')).toEqual([
    { dir: '/h/.claude' },
    { dir: '\\\\srv\\a\\.claude-x', tag: 'x' },
    { dir: '\\\\srv\\b\\.claude-y', tag: 'y' },
  ])
})

test('one pid in several registries keeps only the most recently active row', async () => {
  const mk = (configDir: string, lastActive: number) => ({ configDir, row: { ...base, pid: 7, status: 'idle', lastActive } })
  const found = [mk('/own', 100), mk('/other', 900), { configDir: '/own', row: { ...base, pid: 8, status: 'idle', lastActive: 1 } }]

  expect(newestPerPid(found).map(f => `${f.configDir}:${f.row.pid}`)).toEqual(['/other:7', '/own:8'])
  // A tie keeps the first, the own dir's.
  expect(newestPerPid([mk('/own', 5), mk('/other', 5)]).map(f => f.configDir)).toEqual(['/own'])
})


// --- stray panes: registered in another account, or the agents view ---------------------

const PANES = [
  'cc-own-1\t101\t2.1.289\t/r/mine\t1791148000',
  'cc-work-1\t777\t2.1.289\t/r/work\t1791148100',
  'cc-agents\t800\t2.1.289\t/r/x\t1791148200',
  'cc-new-1\t900\t2.1.289\t/r/new\t1791148300',
].join('\n')
const REGISTERED = { pids: new Set([101]), tmuxNames: new Set(['cc-own-1']) }

test('a pane registered in another account is labelled so, not left as a startup prompt', async () => {
  const rows = strayRows(PANES, REGISTERED, { elsewhere: new Map([[777, 'work']]), agentsView: new Set<number>() })
  const work = rows.find(r => r.pid === 777)!

  expect(work.note).toBe('running in another account (work) — set ROSTER_CONFIG_DIRS to list it')
  expect(work.waitingFor).toBeUndefined()
  expect(work.status).not.toBe('waiting')
  expect(isStray(work)).toBe(true)   // no kill is ever offered for it
})

test('a pane running `claude agents` is the agents view, not a startup prompt', async () => {
  const rows = strayRows(PANES, REGISTERED, { elsewhere: new Map(), agentsView: new Set([800]) })
  const agents = rows.find(r => r.pid === 800)!

  expect(agents.note).toBe('agents view')
  expect(agents.status).not.toBe('waiting')
  expect(isStray(agents)).toBe(true)
})

test('only a pane that is neither registered anywhere nor the agents view is a startup prompt', async () => {
  const rows = strayRows(PANES, REGISTERED, { elsewhere: new Map([[777, 'work']]), agentsView: new Set([800]) })
  const byPid = Object.fromEntries(rows.map(r => [r.pid, r.waitingFor]))

  expect(rows.map(r => r.pid)).toEqual([777, 800, 900])
  expect(byPid[900]).toContain('startup prompt')
  expect(byPid[777]).toBeUndefined()
  expect(rows.find(r => r.pid === 900)!.status).toBe('waiting')
})

test('without that context every unregistered pane is still a startup prompt', async () => {
  expect(strayRows(PANES, REGISTERED).map(r => r.waitingFor)).toEqual([
    expect.stringContaining('startup prompt'), expect.stringContaining('startup prompt'), expect.stringContaining('startup prompt'),
  ])
})

test('the agents view is recognised from the process arguments', async () => {
  const ps = [
    '  800 /Users/me/.local/share/claude/versions/2.1.289 agents',
    '  801 claude agents --foo',
    '  802 /Users/me/.local/share/claude/versions/2.1.289',
    '  803 /Users/me/.local/bin/claude --resume agents',
    '  804 node /x/agents.js',
    '',
  ].join('\n')

  expect([...agentsViewPidsIn(ps)].sort()).toEqual([800, 801])
})

test('the registry tmux field is <session>:@W.%P and only the session part is the name', async () => {
  expect(toRow({ pid: 5, cwd: '/r', tmux: 'cc-wf-claude-market-3:@29.%29' })?.tmux).toBe('cc-wf-claude-market-3')
  expect(toRow({ pid: 5, cwd: '/r', tmux: 'plain' })?.tmux).toBe('plain')
  // the name fallback then matches tmux list-panes' session name
  const panes = 'cc-wf-claude-market-3\t41000\t2.1.289\t/r\t1791148000'
  const registered = toRow({ pid: 5, cwd: '/r', tmux: 'cc-wf-claude-market-3:@29.%29' })!
  expect(strayRows(panes, { pids: new Set([5]), tmuxNames: new Set([registered.tmux!]) })).toEqual([])
})

test('another-account dirs are the HOME dirs starting .claude, minus those already listed', async () => {
  const names = ['.claude', '.claude-work', '.claude-personal', '.config', 'claude', '.claudeX']
  expect(otherClaudeDirs('/home', names, ['/home/.claude', '/home/.claude-personal/'])).toEqual(['/home/.claude-work', '/home/.claudeX'])
})
