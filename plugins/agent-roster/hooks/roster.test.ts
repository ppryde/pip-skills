import { expect, test } from 'claude-code/testing'

import {
  ago,
  headline,
  lastPromptOf,
  matchTarget,
  projectSlug,
  repoOf,
  sorted,
  summary,
  toRow,
} from './register'

test('the headline counts sessions, waiting and busy', async () => {
  expect(headline([])).toBe('0 sessions · 0 waiting · 0 busy')
})

test('summarises the roster as text, the last prompt under its session', async () => {
  const base = { sessionId: '', account: 'personal', kind: 'interactive', lastActive: 0 }
  const text = summary(
    [
      {
        ...base,
        pid: 1,
        tmux: 'cc-ledger-poc-2',
        cwd: '/r/ledger-poc',
        repo: 'ledger-poc',
        status: 'waiting',
        waitingFor: 'input needed',
        lastPrompt: 'add demo cards',
      },
      { ...base, pid: 2, account: 'work', cwd: '/r/warehouse', repo: 'warehouse', status: 'idle' },
    ],
    120_000,
  )

  expect(text).toBe(
    [
      '2 sessions · 1 waiting · 0 busy',
      '◆ cc-ledger-poc-2 · ledger-poc · waiting: input needed · 2m',
      '   › add demo cards',
      '○ pid 2 · warehouse · idle · 2m · work',
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

test('takes the last last-prompt row, whitespace collapsed', async () => {
  const lines = [
    '{"type":"last-prompt","lastPrompt":"first"}',
    '{"type":"last-prompt","lastPrompt":"fix the\\n  flaky   test"}',
    'not json',
  ].join('\n')

  expect(lastPromptOf(lines)).toBe('fix the flaky test')
  expect(lastPromptOf('')).toBe(undefined)
})

test('waiting sessions first, then busy, then the rest by last active', async () => {
  const base = { sessionId: '', account: 'personal', cwd: '/r', repo: 'r', kind: 'interactive' }
  const rows = sorted([
    { ...base, pid: 1, status: 'idle', lastActive: 50 },
    { ...base, pid: 2, status: 'busy', lastActive: 10 },
    { ...base, pid: 3, status: 'idle', lastActive: 90 },
    { ...base, pid: 4, status: 'waiting', lastActive: 5 },
  ])

  expect(rows.map(r => r.pid)).toEqual([4, 2, 3, 1])
  expect(ago(0, 90_000)).toBe('2m')
  expect(ago(0, 3 * 86_400_000)).toBe('3d')
})

test('a kill target is a tmux name or a pid, and a name on both accounts is two matches', async () => {
  const base = { sessionId: '', cwd: '/r', repo: 'r', kind: 'interactive', status: 'idle', lastActive: 0 }
  const rows = [
    { ...base, pid: 23156, account: 'personal', tmux: 'cc-take-home-tasks-2' },
    { ...base, pid: 83438, account: 'work', tmux: 'cc-take-home-tasks-2' },
    { ...base, pid: 75378, account: 'personal' },
  ]

  expect(matchTarget(rows, 'cc-take-home-tasks-2').map(r => r.pid)).toEqual([23156, 83438])
  expect(matchTarget(rows, '83438').map(r => r.pid)).toEqual([83438])
  expect(matchTarget(rows, '75378').map(r => r.pid)).toEqual([75378])
  expect(matchTarget(rows, 'cc-take-home')).toEqual([])
})
