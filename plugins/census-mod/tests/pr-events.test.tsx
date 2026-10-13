import { expect, test } from 'claude-code/testing'
import { START, classicStart, world, GH_ON } from './world'
import type { World } from './world'

const SEC = 1000
const ghRuns = (w: World) => w.runs.filter(r => r.argv[0] === 'gh')
const bash = (command: string) => ({ tool: 'Bash', command }) as never
const op = (w: World, gitOperation: object) => { w.toolResult.value = { stdout: '', stderr: '', interrupted: false, gitOperation } }
const rec = (w: World, key = 'pr:o/r#main') => w.store.get(key) as Record<string, unknown> | undefined
const NOPR = { 'census-mod:setup': { offered: true, pr: false } } // "never call gh": the events still speak


test('a gh pr create reported by the engine shows the PR at once, with no gh call (the PR setting is off)', async ($, on) => {
  const w = world(on)
  w.store.set('census-mod:setup', NOPR['census-mod:setup'])
  w.remote.value = 'git@github.com:o/r.git\n'
  await $.session.start(START)
  await w.clock.advance(0)

  op(w, { pr: { number: 102, url: 'https://github.com/o/r/pull/102', action: 'created' } })
  await $.tool.call(bash('gh pr create --fill'))
  await w.clock.advance(2 * SEC)

  expect(rec(w)).toMatchObject({ number: 102, url: 'https://github.com/o/r/pull/102', state: 'open', lastAction: 'created', source: 'event', sessionId: 's1' })
  expect(ghRuns(w)).toHaveLength(0)
  expect(w.ingests.at(-1)?.payload).toMatchObject({ pr: { number: 102, url: 'https://github.com/o/r/pull/102' }, census_mod: { event: 'pr' } })
})

test('--draft sets the review state to draft; ready moves it to pending', async ($, on) => {
  const w = world(on)
  w.store.set('census-mod:setup', NOPR['census-mod:setup'])
  w.remote.value = 'https://github.com/o/r.git\n'
  await $.session.start(START)
  await w.clock.advance(0)

  op(w, { pr: { number: 7, url: 'u', action: 'created' } })
  await $.tool.call(bash('gh pr create --draft --fill'))
  await w.clock.advance(2 * SEC)
  expect(w.ingests.at(-1)?.payload.pr).toMatchObject({ number: 7, review_state: 'draft' })

  op(w, { pr: { number: 7, action: 'ready' } }) // ready carries no url: the old one stays
  await $.tool.call(bash('gh pr ready 7'))
  await w.clock.advance(2 * SEC)
  expect(rec(w)).toMatchObject({ url: 'u', review: 'pending', lastAction: 'ready' })
  expect(w.ingests.at(-1)?.payload.pr).toMatchObject({ number: 7, url: 'u', review_state: 'pending' })
})

test('close and merge end the PR: the payload drops it', async ($, on) => {
  const w = world(on)
  w.store.set('census-mod:setup', NOPR['census-mod:setup'])
  w.remote.value = 'git@github.com:o/r.git\n'
  await $.session.start(START)
  await w.clock.advance(0)
  op(w, { pr: { number: 7, url: 'u', action: 'created' } })
  await $.tool.call(bash('gh pr create --fill'))
  await w.clock.advance(2 * SEC)

  op(w, { pr: { number: 7, action: 'closed' } })
  await $.tool.call(bash('gh pr close 7 --delete-branch'))
  await w.clock.advance(2 * SEC)
  expect(rec(w)).toMatchObject({ state: 'closed', url: 'u' })
  expect(w.ingests.at(-1)?.payload).not.toHaveProperty('pr')

  op(w, { pr: { number: 7, action: 'reopened' } })
  await $.tool.call(bash('gh pr reopen 7'))
  await w.clock.advance(2 * SEC)
  expect(w.ingests.at(-1)?.payload.pr).toMatchObject({ number: 7 })

  op(w, { pr: { number: 7, action: 'merged' } })
  await $.tool.call(bash('gh pr merge 7'))
  await w.clock.advance(2 * SEC)
  expect(w.ingests.at(-1)?.payload).not.toHaveProperty('pr')
})

test('a PR is matched by number first: closing it from another branch updates the branch it belongs to', async ($, on) => {
  const w = world(on)
  w.store.set('census-mod:setup', NOPR['census-mod:setup'])
  w.remote.value = 'git@github.com:o/r.git\n'
  w.store.set('pr:o/r#feat', { number: 9, url: 'u9', state: 'open', lastAction: 'created', source: 'event', at: 1, sessionId: 'x', worktree: '/w' })
  await $.session.start(START)
  await w.clock.advance(0)

  op(w, { pr: { number: 9, action: 'closed' } })
  await $.tool.call(bash('gh pr close 9'))
  await w.clock.advance(2 * SEC)

  expect(rec(w, 'pr:o/r#feat')).toMatchObject({ state: 'closed' })
  expect(rec(w, 'pr:o/r#main')).toBeUndefined() // the current branch was not touched
})

test('only a created PR falls back to the current branch: a comment on an unknown PR records nothing', async ($, on) => {
  const w = world(on)
  w.store.set('census-mod:setup', NOPR['census-mod:setup'])
  w.remote.value = 'git@github.com:o/r.git\n'
  await $.session.start(START)
  await w.clock.advance(0)

  op(w, { pr: { number: 55, url: 'u', action: 'commented' } })
  await $.tool.call(bash('gh pr comment 55 --body hi'))
  await w.clock.advance(2 * SEC)
  expect([...w.store.keys()].filter(k => k.startsWith('pr:'))).toEqual([])
})

test('a push marks the branch\'s record stale; the next PR word clears it', async ($, on) => {
  const w = world(on)
  w.store.set('census-mod:setup', NOPR['census-mod:setup'])
  w.remote.value = 'git@github.com:o/r.git\n'
  await $.session.start(START)
  await w.clock.advance(0)
  op(w, { pr: { number: 7, url: 'u', action: 'created' } })
  await $.tool.call(bash('gh pr create --fill'))

  op(w, { push: { branch: 'main' } })
  await $.tool.call(bash('git push'))
  await w.clock.advance(2 * SEC)
  expect(rec(w)).toMatchObject({ stale: true })

  op(w, { pr: { number: 7, action: 'ready' } })
  await $.tool.call(bash('gh pr ready 7'))
  await w.clock.advance(2 * SEC)
  expect(rec(w)?.stale).toBeUndefined()
})

test('a fresh bind of the branch reads the record back with no gh call', async ($, on) => {
  const w = world(on)
  w.store.set('census-mod:setup', NOPR['census-mod:setup'])
  w.remote.value = 'git@github.com:o/r.git\n'
  w.store.set('pr:o/r#main', { number: 7, url: 'u', state: 'open', review: 'approved', lastAction: 'ready', source: 'event', at: 1_791_000_000_000 - 1000, sessionId: 'old', worktree: '/repo' })
  await $.session.start(START)
  await w.clock.advance(2 * SEC)

  expect(ghRuns(w)).toHaveLength(0)
  expect(w.ingests.at(-1)?.payload.pr).toMatchObject({ number: 7, review_state: 'approved' })

  w.sessionId.value = 's2'
  await $.classic.SessionStart(classicStart('clear', 's2'))
  await w.clock.advance(6 * SEC)
  expect(w.ingests.filter(i => i.payload.session_id === 's2').at(-1)?.payload.pr).toMatchObject({ number: 7 })
})

test('no origin remote: nothing is recorded and nothing breaks', async ($, on) => {
  const w = world(on)
  w.store.set('census-mod:setup', NOPR['census-mod:setup'])
  await $.session.start(START)
  await w.clock.advance(0)
  op(w, { pr: { number: 7, url: 'u', action: 'created' } })
  await $.tool.call(bash('gh pr create --fill'))
  await w.clock.advance(2 * SEC)

  expect([...w.store.keys()].filter(k => k.startsWith('pr:'))).toEqual([])
  expect(w.ingests.at(-1)?.payload).not.toHaveProperty('pr')
})

test('a result without gitOperation (gh pr view, checkout) changes nothing', async ($, on) => {
  const w = world(on)
  w.store.set('census-mod:setup', NOPR['census-mod:setup'])
  w.remote.value = 'git@github.com:o/r.git\n'
  await $.session.start(START)
  await w.clock.advance(0)
  w.toolResult.value = { stdout: 'title: x', stderr: '', interrupted: false }
  await $.tool.call(bash('gh pr view 7'))
  await w.clock.advance(2 * SEC)
  expect([...w.store.keys()].filter(k => k.startsWith('pr:'))).toEqual([])
})

test('with gh on, an event record is not flipped to closed by a gh list that has not caught up yet', async ($, on) => {
  const w = world(on)
  w.store.set('census-mod:setup', GH_ON)
  w.remote.value = 'git@github.com:o/r.git\n'
  w.gh.stdout = '[]' // GitHub has not listed the new PR yet
  await $.session.start(START)
  await w.clock.advance(2 * SEC)
  op(w, { pr: { number: 7, url: 'u', action: 'created' } })
  await $.tool.call(bash('gh pr create --fill')) // also asks gh, which says "none"
  await w.clock.advance(2 * SEC)

  expect(ghRuns(w).length).toBeGreaterThan(0)
  expect(rec(w)).toMatchObject({ number: 7, state: 'open' })
  expect(w.ingests.at(-1)?.payload.pr).toMatchObject({ number: 7 })
})

test('gh, when it answers, is recorded as the newest word on the branch', async ($, on) => {
  const w = world(on)
  w.store.set('census-mod:setup', GH_ON)
  w.remote.value = 'git@github.com:o/r.git\n'
  w.gh.stdout = JSON.stringify([{ number: 102, url: 'https://github.com/o/r/pull/102', reviewDecision: 'APPROVED' }])
  await $.session.start(START)
  await w.clock.advance(2 * SEC)

  expect(rec(w)).toMatchObject({ number: 102, state: 'open', review: 'approved', source: 'gh' })
  expect(w.ingests.at(-1)?.payload.pr).toMatchObject({ number: 102, review_state: 'approved' })
})

test('a failing gh after a close does not reopen the PR (the event record stands)', async ($, on) => {
  const w = world(on)
  w.store.set('census-mod:setup', GH_ON)
  w.remote.value = 'git@github.com:o/r.git\n'
  w.gh.stdout = JSON.stringify([{ number: 7, url: 'u', reviewDecision: 'APPROVED' }])
  await $.session.start(START)
  await w.clock.advance(2 * SEC)
  expect(w.ingests.at(-1)?.payload.pr).toMatchObject({ number: 7 })

  op(w, { pr: { number: 7, action: 'closed' } })
  w.gh.exitCode = 1 // gh now errors (e.g. a token without the GraphQL scope)
  await $.tool.call(bash('gh pr close 7'))
  await w.clock.advance(60 * SEC)
  expect(rec(w)).toMatchObject({ state: 'closed' })
  expect(w.ingests.at(-1)?.payload).not.toHaveProperty('pr')
})

test('a gh answer with no review decision clears draft and pending', async ($, on) => {
  const w = world(on)
  w.store.set('census-mod:setup', GH_ON)
  w.remote.value = 'git@github.com:o/r.git\n'
  w.gh.stdout = '[]'
  await $.session.start(START)
  await w.clock.advance(2 * SEC)
  op(w, { pr: { number: 7, url: 'u', action: 'created' } })
  await $.tool.call(bash('gh pr create --draft --fill'))
  await w.clock.advance(2 * SEC)
  expect(rec(w)).toMatchObject({ review: 'draft' })

  w.gh.stdout = JSON.stringify([{ number: 7, url: 'u', reviewDecision: '' }]) // marked ready on github.com
  op(w, { push: { branch: 'main' } })
  await $.tool.call(bash('git push'))
  await w.clock.advance(60 * SEC)
  expect(rec(w)).not.toHaveProperty('review')
})
