import { expect, test } from 'claude-code/testing'

import {
  ago,
  grouped,
  headline,
  matchTarget,
  projectSlug,
  repoOf,
  repoTabs,
  sorted,
  summary,
  tabLabel,
  toRow,
  transcriptFacts,
} from './register'

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
  expect(tabs.map(t => tabLabel(t, t.repo))).toEqual([
    'pip-skills ◆1 ●1',
    'ledger-poc ◆1',
    'warehouse 1',
    'agents.md 1',
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
