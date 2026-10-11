import { expect, test } from 'claude-code/testing'
import { applyPatch, gitOperationOf, hasDraftFlag, markStale, patchFor, prKey, repoOf, toPr } from '../plugin/core/prstate'
import type { PrRecord } from '../plugin/core/prstate'
import { SEGMENTS } from '../plugin/core/render'

const CTX = { sessionId: 's1', worktree: '/repo' }
const T0 = 1_791_000_000_000

test('owner/name comes from https, ssh and scp-like origins, with or without .git', () => {
  expect(repoOf('https://github.com/ppryde/pip-skills.git')).toBe('ppryde/pip-skills')
  expect(repoOf('https://github.com/ppryde/pip-skills')).toBe('ppryde/pip-skills')
  expect(repoOf('git@github.com:ppryde/pip-skills.git\n')).toBe('ppryde/pip-skills')
  expect(repoOf('ssh://git@github.com:22/o/r.git')).toBe('o/r')
  expect(repoOf('https://user:tok@github.com/o/r')).toBe('o/r') // only owner/name is kept, never the credentials
  expect(repoOf('/local/path/repo')).toBeNull()
  expect(repoOf('')).toBeNull()
  expect(prKey('o/r', 'feat/x')).toBe('pr:o/r#feat/x')
})

test('only a well-formed gitOperation is read; anything else is no operation', () => {
  expect(gitOperationOf('ok')).toBeNull()
  expect(gitOperationOf(null)).toBeNull()
  expect(gitOperationOf({ stdout: '' })).toBeNull()
  expect(gitOperationOf({ gitOperation: { commit: { sha: 'a', kind: 'committed' } } })).toBeNull()
  expect(gitOperationOf({ gitOperation: { push: { branch: 'feat' } } })).toEqual({ push: { branch: 'feat' } })
  expect(gitOperationOf({ gitOperation: { pr: { number: 7, url: 'https://x/pull/7', action: 'created' } } })).toEqual({ pr: { number: 7, url: 'https://x/pull/7', action: 'created' } })
  expect(gitOperationOf({ gitOperation: { pr: { number: 7, action: 'bogus' } } })).toBeNull()
  expect(gitOperationOf({ gitOperation: { pr: { number: -1, action: 'closed' } } })).toBeNull()
  expect(gitOperationOf({ gitOperation: { pr: { number: '7', action: 'closed' } } })).toBeNull()
})

test('created opens the PR (draft only when --draft was passed); ready, draft, closed, merged and reopened set state or review', () => {
  expect(patchFor({ number: 7, url: 'u', action: 'created' }, false)).toEqual({ number: 7, url: 'u', lastAction: 'created', state: 'open' })
  expect(patchFor({ number: 7, action: 'created' }, true)).toMatchObject({ state: 'open', review: 'draft' })
  expect(patchFor({ number: 7, action: 'ready' }, false)).toMatchObject({ state: 'open', review: 'pending' })
  expect(patchFor({ number: 7, action: 'draft' }, false)).toMatchObject({ state: 'open', review: 'draft' })
  expect(patchFor({ number: 7, action: 'closed' }, false)).toMatchObject({ state: 'closed' })
  expect(patchFor({ number: 7, action: 'merged' }, false)).toMatchObject({ state: 'merged' })
  expect(patchFor({ number: 7, action: 'reopened' }, false)).toMatchObject({ state: 'open' })
})

test('commented, edited and auto-merge touch only the time and the action', () => {
  for (const action of ['commented', 'edited', 'auto-merge-enabled', 'auto-merge-disabled']) {
    const p = patchFor({ number: 7, action }, true)
    expect(p).toEqual({ number: 7, lastAction: action })
  }
  const open = applyPatch(undefined, patchFor({ number: 7, url: 'u', action: 'created' }, true), T0, CTX)!
  const after = applyPatch(open, patchFor({ number: 7, action: 'commented' }, false), T0 + 5, CTX)!
  expect(after).toMatchObject({ state: 'open', review: 'draft', url: 'u', lastAction: 'commented', at: T0 + 5 })
})

test('a field an event lacks keeps its old value (a close without a url keeps the url)', () => {
  const open = applyPatch(undefined, patchFor({ number: 7, url: 'https://x/pull/7', action: 'created' }, false), T0, CTX)!
  const closed = applyPatch(open, patchFor({ number: 7, action: 'closed' }, false), T0 + 1, CTX)!
  expect(closed).toMatchObject({ state: 'closed', url: 'https://x/pull/7', lastAction: 'closed' })
})

test('the newest at wins: an older word for the same PR changes nothing', () => {
  const closed = applyPatch(undefined, patchFor({ number: 7, action: 'closed' }, false), T0, CTX)!
  expect(applyPatch(closed, patchFor({ number: 7, action: 'ready' }, false), T0 - 1, CTX)).toBe(closed)
})

test('a different PR number replaces the record rather than inheriting its fields', () => {
  const a = applyPatch(undefined, { ...patchFor({ number: 7, url: 'u7', action: 'created' }, false), review: 'approved' }, T0, CTX)!
  const b = applyPatch(a, patchFor({ number: 8, action: 'created' }, false), T0 + 1, CTX)!
  expect(b).toMatchObject({ number: 8, state: 'open' })
  expect(b.url).toBeUndefined()
  expect(b.review).toBeUndefined()
})

test('a push marks the record stale; the next word about the PR clears it', () => {
  const rec = applyPatch(undefined, patchFor({ number: 7, action: 'created' }, false), T0, CTX)!
  const stale = markStale(rec)
  expect(stale.stale).toBe(true)
  expect(markStale(stale)).toBe(stale)
  const fresh = applyPatch(stale, patchFor({ number: 7, action: 'ready' }, false), T0 + 1, CTX)!
  expect(fresh.stale).toBeUndefined()
})

test('only an open PR is drawn; stale or a day old is dimmed', () => {
  const rec = (over: Partial<PrRecord>): PrRecord => ({ number: 7, state: 'open', lastAction: 'created', source: 'event', at: T0, sessionId: 's', worktree: '/r', ...over })
  expect(toPr(undefined, T0)).toBeNull()
  expect(toPr(rec({ state: 'closed' }), T0)).toBeNull()
  expect(toPr(rec({ state: 'merged' }), T0)).toBeNull()
  expect(toPr(rec({ url: 'u', review: 'draft' }), T0 + 1000)).toEqual({ number: 7, url: 'u', reviewState: 'draft' })
  expect(toPr(rec({ stale: true }), T0)).toMatchObject({ stale: true })
  expect(toPr(rec({}), T0 + 25 * 3600_000)).toMatchObject({ stale: true })
})

test('--draft is spotted as a flag, not inside a title', () => {
  expect(hasDraftFlag('gh pr create --draft --fill')).toBe(true)
  expect(hasDraftFlag('gh pr create -d')).toBe(true)
  expect(hasDraftFlag('gh pr create --title "no --draftish"')).toBe(false)
  expect(hasDraftFlag('gh pr create --fill')).toBe(false)
})

test('an unconfirmed PR is drawn in grey; a confirmed one keeps its review colour', () => {
  const base = { now: 0, ctxPct: null, cache: { hitRatio: null, requests: 0, warm: false, expiresAt: null, misses: 0 }, limits: {}, costUsd: null, durationMs: null, modelName: null, git: null, cwd: '/', env: {} }
  const stale = SEGMENTS.pr!({ ...base, pr: { number: 7, url: '', reviewState: 'approved', stale: true } } as never)
  expect(stale).toEqual([[{ t: '🔀 #7 approved', tone: 'grey' }]])
  const fresh = SEGMENTS.pr!({ ...base, pr: { number: 7, url: '', reviewState: 'approved' } } as never)
  expect(fresh[0]?.some(r => r.tone === 'green')).toBe(true)
})
