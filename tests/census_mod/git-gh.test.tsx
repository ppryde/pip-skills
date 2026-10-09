import { expect, test } from 'claude-code/testing'
import { START, classicStart, world } from './world'
import type { World } from './world'

const SEC = 1000
const MIN = 60 * SEC
const gitStatusRuns = (w: World) => w.runs.filter(r => r.argv[0] === 'git' && r.argv.includes('status'))
const ghRuns = (w: World) => w.runs.filter(r => r.argv[0] === 'gh')
const PR = JSON.stringify([{ number: 102, url: 'https://github.com/o/r/pull/102', reviewDecision: 'APPROVED' }])
const call = (tool: string, extra: object = {}) => ({ tool, ...extra }) as never

test('git is run once at the start, with exactly the minimal argv and the session cwd', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await w.clock.advance(0)

  expect(gitStatusRuns(w)).toHaveLength(1)
  expect(gitStatusRuns(w)[0]?.argv).toEqual(['git', '--no-optional-locks', 'status', '--porcelain=2', '--branch', '-uno'])
  expect(gitStatusRuns(w)[0]?.cwd).toBe('/repo')
})

test('git is re-asked after an Edit, Write or Bash call, a HEAD/index change and a cwd change; never after a Read', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await w.clock.advance(0)
  const base = gitStatusRuns(w).length

  await $.tool.call(call('Read', { file_path: '/repo/a' }))
  await w.clock.advance(5 * SEC)
  expect(gitStatusRuns(w)).toHaveLength(base)

  for (const [i, trigger] of [
    () => $.tool.call(call('Edit', { file_path: '/repo/a' })),
    () => $.tool.call(call('Write', { file_path: '/repo/a' })),
    () => $.tool.call(call('Bash', { command: 'ls' })),
    () => $.classic.FileChanged({ file_path: '/repo/.git/HEAD', event: 'change' } as never),
    () => $.classic.CwdChanged({ old_cwd: '/repo', new_cwd: '/repo/sub' } as never),
  ].entries()) {
    await trigger()
    await w.clock.advance(1100)
    expect(gitStatusRuns(w)).toHaveLength(base + i + 1)
  }
})

test('git runs coalesce to one a second', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await w.clock.advance(0)
  const base = gitStatusRuns(w).length
  for (let i = 0; i < 6; i++) await $.tool.call(call('Edit', { file_path: '/repo/a' }))
  await w.clock.advance(0)
  await w.clock.advance(1100)
  expect(gitStatusRuns(w).length).toBeLessThanOrEqual(base + 2)
})

test('HEAD and the index are watched through classic SessionStart (git dir resolved for worktrees)', async ($, on) => {
  const w = world(on)
  w.git.dir = '/repo/.git/worktrees/w\n/wt\n'
  await $.session.start(START)
  const r = (await $.classic.SessionStart(classicStart('startup'))) as { watchPaths?: string[] }

  expect(r.watchPaths).toEqual(['/repo/.git/worktrees/w/HEAD', '/repo/.git/worktrees/w/index'])
  await w.clock.advance(0)
  expect(w.ingests.at(-1)?.payload.worktree).toEqual({ path: '/wt' })
})

test('gh is asked for the branch\'s open PR at the start: exact argv, cwd the worktree; the answer lands in the payload', async ($, on) => {
  const w = world(on)
  w.gh.stdout = PR
  await $.session.start(START)
  await w.clock.advance(0)
  await w.clock.advance(2 * SEC)

  expect(ghRuns(w)).toHaveLength(1)
  expect(ghRuns(w)[0]?.argv).toEqual(['gh', 'pr', 'list', '--head', 'main', '--state', 'open', '--limit', '1', '--json', 'number,url,reviewDecision'])
  expect(ghRuns(w)[0]?.cwd).toBe('/repo')
  expect(ghRuns(w)[0]?.timeoutMs).toBe(5000)
  expect(w.ingests.at(-1)?.payload).toMatchObject({ pr: { number: 102, url: 'https://github.com/o/r/pull/102', review_state: 'approved' }, census_mod: { event: 'pr' } })
})

test('gh runs after a Bash git push or gh pr, not after any other command, and on a branch change', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await w.clock.advance(0)
  const base = ghRuns(w).length

  await $.tool.call(call('Bash', { command: 'ls -la' }))
  await w.clock.advance(2 * SEC)
  expect(ghRuns(w)).toHaveLength(base)

  await $.tool.call(call('Bash', { command: 'git push -u origin feat' }))
  await w.clock.advance(2 * SEC)
  expect(ghRuns(w)).toHaveLength(base + 1)
  await $.tool.call(call('Bash', { command: 'gh pr create --fill' }))
  await w.clock.advance(2 * SEC)
  expect(ghRuns(w)).toHaveLength(base + 2)

  w.git.status = '# branch.oid abc\n# branch.head other\n'
  await $.classic.FileChanged({ file_path: '/repo/.git/HEAD', event: 'change' } as never)
  await w.clock.advance(2 * SEC)
  expect(ghRuns(w)).toHaveLength(base + 3)
  expect(ghRuns(w).at(-1)?.argv).toContain('other')
  expect(w.ingests.some(i => i.payload.census_mod.event === 'branch')).toBe(true)
})

test('gh stays quiet on a detached HEAD', async ($, on) => {
  const w = world(on)
  w.git.status = '# branch.oid abc1234def\n# branch.head (detached)\n'
  await $.session.start(START)
  await w.clock.advance(5 * SEC)

  expect(ghRuns(w)).toHaveLength(0)
})

test('a gh failure keeps the cached PR and backs off for 10 minutes', async ($, on) => {
  const w = world(on)
  w.gh.stdout = PR
  await $.session.start(START)
  await w.clock.advance(2 * SEC)
  expect(ghRuns(w)).toHaveLength(1)

  w.gh.exitCode = 1
  await $.tool.call(call('Bash', { command: 'git push' }))
  await w.clock.advance(2 * SEC)
  expect(ghRuns(w)).toHaveLength(2)
  await $.tool.call(call('Bash', { command: 'git push' }))
  await w.clock.advance(5 * MIN)
  expect(ghRuns(w)).toHaveLength(2) // inside the backoff
  expect(w.ingests.at(-1)?.payload.pr).toMatchObject({ number: 102 }) // the cached value stands

  w.gh.exitCode = 0
  w.gh.stdout = '[]'
  await w.clock.advance(5 * MIN + 10 * SEC)
  await $.tool.call(call('Bash', { command: 'git push' }))
  await w.clock.advance(2 * SEC)
  expect(ghRuns(w)).toHaveLength(3)
})

test('gh missing: no PR, one log line, and the backoff holds', async ($, on) => {
  const w = world(on)
  w.gh.throws = true
  await $.session.start(START)
  await w.clock.advance(2 * SEC)
  await $.tool.call(call('Bash', { command: 'git push' }))
  await w.clock.advance(2 * SEC)

  expect(w.logs.filter(l => l.includes('gh unavailable'))).toHaveLength(1)
  expect(ghRuns(w)).toHaveLength(1)
  expect(w.ingests.at(-1)?.payload).not.toHaveProperty('pr')
})

test('a stale PR answer is refreshed on the clock tick, but only while the session is active', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await w.clock.advance(2 * SEC)
  await $.tool.call(call('Edit', { file_path: '/repo/a' })) // activity
  const base = ghRuns(w).length

  await w.clock.advance(9 * MIN)
  expect(ghRuns(w)).toHaveLength(base)
  await $.tool.call(call('Edit', { file_path: '/repo/a' })) // still active
  await w.clock.advance(2 * MIN)
  expect(ghRuns(w)).toHaveLength(base + 1)
  await w.clock.advance(30 * MIN) // idle for half an hour: the tick leaves gh alone
  expect(ghRuns(w)).toHaveLength(base + 1)
})

test('the PR is cached per repo and branch in $.store, so a restart does not re-ask it for nothing', async ($, on) => {
  const w = world(on)
  w.gh.stdout = PR
  await $.session.start(START)
  await w.clock.advance(2 * SEC)

  expect([...w.store.keys()].some(k => k.startsWith('gh:/repo|main'))).toBe(true)
})
