import { expect, test } from 'claude-code/testing'
import { HINT, START, world, GH_ON } from './world'
import type { World } from './world'

// WF-269 round 2: /census-mod:pr-refresh, the status-line command's pr, and the prompt-hint confirmation.
const SEC = 1000
const NOW = 1_791_000_000_000
const SESSION_FILE = '/cfg/census/sessions/s1.json'
const ghRuns = (w: World) => w.runs.filter(r => r.argv[0] === 'gh')
const bash = (command: string) => ({ tool: 'Bash', command }) as never
const op = (w: World, gitOperation: object) => { w.toolResult.value = { stdout: '', stderr: '', interrupted: false, gitOperation } }
const rec = (w: World, key = 'pr:o/r#main') => w.store.get(key) as Record<string, unknown> | undefined
const NO = { offered: true, pr: false }
const refresh = ($: any) => $.command.run({ command: 'pr-refresh', args: '', origin: { kind: 'composer' } }) as Promise<{ text: string }>
const GH = JSON.stringify([{ number: 102, url: 'https://github.com/o/r/pull/102', reviewDecision: 'APPROVED' }])
// What census's ingest leaves beside the payload when a status-line command sent a pr (`at` is epoch seconds).
const lineFile = (pr: object, agoSec = 10) => JSON.stringify({ updated_at: 1, payload: {}, status_line_pr: { ...pr, at: NOW / 1000 - agoSec } })

// ---- /census-mod:pr-refresh ------------------------------------------------------------------------------------------

test('pr-refresh is a registered command; with the PR answer at its default (No) gh is never called until it runs', async ($, on) => {
  const w = world(on)
  w.remote.value = 'git@github.com:o/r.git\n'
  w.gh.stdout = GH
  await $.session.start(START)
  await w.clock.advance(5 * 60 * SEC)
  expect(ghRuns(w)).toHaveLength(0)

  const r = await refresh($)
  await w.clock.advance(2 * SEC)

  expect(ghRuns(w)).toHaveLength(1)
  expect(ghRuns(w)[0]?.argv).toEqual(['gh', 'pr', 'list', '--head', 'main', '--state', 'open', '--limit', '1', '--json', 'number,url,reviewDecision'])
  expect(r.text).toBe('census-mod: PR #102 (approved) is open on main.')
  expect(rec(w)).toMatchObject({ number: 102, state: 'open', review: 'approved', source: 'gh', lastAction: 'gh' })
  expect(w.ingests.at(-1)?.payload.pr).toMatchObject({ number: 102, review_state: 'approved' })

  // it did not turn gh on: a push still asks nothing
  await $.tool.call(bash('git push'))
  await w.clock.advance(60 * SEC)
  expect(ghRuns(w)).toHaveLength(1)
})

test('pr-refresh with no open PR says so', async ($, on) => {
  const w = world(on)
  w.remote.value = 'git@github.com:o/r.git\n'
  w.gh.stdout = '[]'
  await $.session.start(START)
  await w.clock.advance(0)

  expect((await refresh($)).text).toBe('census-mod: no open PR on main.')
})

test('a failing gh changes nothing: the event record stands, and the text says gh did not answer', async ($, on) => {
  const w = world(on)
  w.remote.value = 'git@github.com:o/r.git\n'
  await $.session.start(START)
  await w.clock.advance(0)
  op(w, { pr: { number: 7, url: 'u', action: 'created' } })
  await $.tool.call(bash('gh pr create --fill'))
  await w.clock.advance(2 * SEC)
  const before = JSON.stringify(rec(w))

  w.gh.exitCode = 1
  const r = await refresh($)
  expect(r.text).toBe('census-mod: gh did not answer (is it installed and logged in?), so nothing changed; still showing PR #7.')
  expect(JSON.stringify(rec(w))).toBe(before)

  w.gh.throws = true // gh not installed
  expect((await refresh($)).text).toContain('gh did not answer')
  expect(JSON.stringify(rec(w))).toBe(before)
  expect(w.ingests.at(-1)?.payload.pr).toMatchObject({ number: 7 })
})

test('pr-refresh asks again straight after a failure: the 10 minute backoff is for the automatic lookups', async ($, on) => {
  const w = world(on)
  w.store.set('census-mod:setup', GH_ON)
  w.remote.value = 'git@github.com:o/r.git\n'
  w.gh.exitCode = 1
  await $.session.start(START)
  await w.clock.advance(2 * SEC) // the start lookup fails and backs off
  expect(ghRuns(w)).toHaveLength(1)

  w.gh.exitCode = 0
  w.gh.stdout = GH
  expect((await refresh($)).text).toContain('PR #102')
  expect(ghRuns(w)).toHaveLength(2)
})

test('a detached HEAD has no branch to look up: gh is not run', async ($, on) => {
  const w = world(on)
  w.git.status = '# branch.oid abc1234def\n# branch.head (detached)\n'
  await $.session.start(START)
  await w.clock.advance(0)

  expect((await refresh($)).text).toContain('not on a branch')
  expect(ghRuns(w)).toHaveLength(0)
})

// ---- the status-line command's pr ------------------------------------------------------------------------------------

test('a pr written by a status-line command draws when nothing else knows the branch, with no gh call', async ($, on) => {
  const w = world(on)
  w.store.set('census-mod:setup', NO)
  w.remote.value = 'git@github.com:o/r.git\n'
  w.files.set(SESSION_FILE, lineFile({ number: 42, url: 'https://github.com/o/r/pull/42', review_state: 'approved' }))
  await $.session.start(START)
  await w.clock.advance(2 * SEC)

  expect(w.ingests.at(-1)?.payload.pr).toMatchObject({ number: 42, url: 'https://github.com/o/r/pull/42', review_state: 'approved' })
  expect(ghRuns(w)).toHaveLength(0)
})

test('precedence, payload first: the session\'s own event beats a pr the status line wrote earlier, and keeps beating it', async ($, on) => {
  const w = world(on)
  w.store.set('census-mod:setup', NO)
  w.remote.value = 'git@github.com:o/r.git\n'
  w.files.set(SESSION_FILE, lineFile({ number: 42, url: 'u42' }))
  await $.session.start(START)
  await w.clock.advance(2 * SEC)
  expect(w.ingests.at(-1)?.payload.pr).toMatchObject({ number: 42 })

  op(w, { pr: { number: 7, url: 'u7', action: 'created' } })
  await $.tool.call(bash('gh pr create --fill'))
  await w.clock.advance(2 * SEC)
  expect(w.ingests.at(-1)?.payload.pr).toMatchObject({ number: 7 })

  w.files.set(SESSION_FILE, lineFile({ number: 42, url: 'u42' }, 1)) // the status line writes again, fresher
  await w.clock.advance(31 * SEC)
  expect(w.ingests.at(-1)?.payload.pr).toMatchObject({ number: 7 })
})

test('precedence, event first: a pr the status line writes after the session\'s own event does not replace it', async ($, on) => {
  const w = world(on)
  w.store.set('census-mod:setup', NO)
  w.remote.value = 'git@github.com:o/r.git\n'
  w.store.set('pr:o/r#main', { number: 7, url: 'u7', state: 'open', lastAction: 'created', source: 'event', at: NOW - 1000, sessionId: 'x', worktree: '/repo' })
  await $.session.start(START)
  await w.clock.advance(2 * SEC)
  expect(w.ingests.at(-1)?.payload.pr).toMatchObject({ number: 7 })

  w.files.set(SESSION_FILE, lineFile({ number: 42, url: 'u42' }))
  await w.clock.advance(31 * SEC)
  expect(w.ingests.at(-1)?.payload.pr).toMatchObject({ number: 7 })
  expect(rec(w)).toMatchObject({ number: 7, source: 'event' })
})

test('an event that closed the PR stands: the status line\'s older word does not reopen it', async ($, on) => {
  const w = world(on)
  w.store.set('census-mod:setup', NO)
  w.remote.value = 'git@github.com:o/r.git\n'
  w.store.set('pr:o/r#main', { number: 7, url: 'u7', state: 'closed', lastAction: 'closed', source: 'event', at: NOW - 1000, sessionId: 'x', worktree: '/repo' })
  w.files.set(SESSION_FILE, lineFile({ number: 7, url: 'u7' }))
  await $.session.start(START)
  await w.clock.advance(2 * SEC)

  expect(w.ingests.at(-1)?.payload).not.toHaveProperty('pr')
})

test('the status line\'s pr beats gh\'s record', async ($, on) => {
  const w = world(on)
  w.store.set('census-mod:setup', NO)
  w.remote.value = 'git@github.com:o/r.git\n'
  w.store.set('pr:o/r#main', { number: 9, url: 'u9', state: 'open', review: 'pending', lastAction: 'gh', source: 'gh', at: NOW - 1000, sessionId: 'x', worktree: '/repo' })
  w.files.set(SESSION_FILE, lineFile({ number: 42, url: 'u42', review_state: 'approved' }))
  await $.session.start(START)
  await w.clock.advance(2 * SEC)

  expect(w.ingests.at(-1)?.payload.pr).toMatchObject({ number: 42, review_state: 'approved' })
})

test('a status-line word older than five minutes (the command is not running) and a malformed one are ignored', async ($, on) => {
  const w = world(on)
  w.store.set('census-mod:setup', NO)
  w.remote.value = 'git@github.com:o/r.git\n'
  w.files.set(SESSION_FILE, lineFile({ number: 42 }, 6 * 60))
  await $.session.start(START)
  await w.clock.advance(2 * SEC)
  expect(w.ingests.at(-1)?.payload).not.toHaveProperty('pr')

  w.files.set(SESSION_FILE, '{not json')
  await w.clock.advance(31 * SEC)
  expect(w.ingests.at(-1)?.payload).not.toHaveProperty('pr')
})

// ---- the prompt hint's "PR #N" ---------------------------------------------------------------------------------------

const HINT_ON = { CLAUDE_CONFIG_DIR: '/cfg', HOME: '/home/u', CENSUS_MOD_PR_HINT: '1' }
const stale = { number: 7, url: 'u7', state: 'open', review: 'pending', lastAction: 'created', source: 'event', stale: true, at: NOW - 3600_000, sessionId: 'x', worktree: '/repo' }

test('with the setting on, the hint naming the recorded PR confirms it: no longer unconfirmed, source kept', async ($, on) => {
  const w = world(on, { env: HINT_ON })
  w.store.set('census-mod:setup', NO)
  w.remote.value = 'git@github.com:o/r.git\n'
  w.store.set('pr:o/r#main', stale)
  await $.session.start(START)
  await w.clock.advance(2 * SEC)
  expect(rec(w)).toMatchObject({ stale: true })

  const ui = await $.ui.mount(HINT({ hint: 'PR #7 · ? for shortcuts' }))
  await ui.drawn()
  await w.clock.advance(2 * SEC)

  expect(rec(w)).toMatchObject({ number: 7, state: 'open', source: 'event', lastAction: 'hint' })
  expect(rec(w)?.at).toBeGreaterThan(NOW)
  expect(rec(w)).not.toHaveProperty('stale')
  await ui.unmount()
})

test('off by default: the same hint changes nothing', async ($, on) => {
  const w = world(on)
  w.store.set('census-mod:setup', NO)
  w.remote.value = 'git@github.com:o/r.git\n'
  w.store.set('pr:o/r#main', stale)
  await $.session.start(START)
  await w.clock.advance(2 * SEC)
  const ui = await $.ui.mount(HINT({ hint: 'PR #7 · ? for shortcuts' }))
  await ui.drawn()
  await w.clock.advance(2 * SEC)

  expect(rec(w)).toEqual(stale)
  await ui.unmount()
})

test('the hint never closes, reopens or starts a record: another number, a closed record, or no record are left alone', async ($, on) => {
  const w = world(on, { env: HINT_ON })
  w.store.set('census-mod:setup', NO)
  w.remote.value = 'git@github.com:o/r.git\n'
  const closed = { ...stale, state: 'closed' }
  w.store.set('pr:o/r#main', closed)
  await $.session.start(START)
  await w.clock.advance(2 * SEC)

  let ui = await $.ui.mount(HINT({ hint: 'PR #7' }))
  await ui.drawn()
  expect(rec(w)).toEqual(closed)
  await ui.unmount()

  w.store.set('pr:o/r#main', stale)
  ui = await $.ui.mount(HINT({ hint: 'PR #8' }))
  await ui.drawn()
  expect(rec(w)).toEqual(stale)
  await ui.unmount()

  w.store.delete('pr:o/r#main')
  ui = await $.ui.mount(HINT({ hint: 'PR #7' }))
  await ui.drawn()
  expect(rec(w)).toBeUndefined()
  await ui.unmount()
})
