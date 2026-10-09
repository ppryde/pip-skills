import { expect, test } from 'claude-code/testing'
import { EMPTY_COUNTERS, addTurn, compacted, withTtl } from '../../plugins/census-mod/core/cache'
import { buildPayload, modelOf, rateLimitsOf } from '../../plugins/census-mod/core/payload'
import type { Snap } from '../../plugins/census-mod/core/types'

const T0 = 1_791_000_000_000
const USAGE = { input_tokens: 2, output_tokens: 100, cache_read_input_tokens: 90, cache_creation_input_tokens: 8 }

const snap = (over: Partial<Snap> = {}): Snap => ({
  sessionId: 's1', transcriptPath: '/cfg/projects/-repo/s1.jsonl', cwd: '/repo', worktreePath: null, version: '2.1.289',
  model: modelOf('claude-opus-5-5[1m]'), sessionName: 'census mod', ctxPct: 9, ctxWindow: 1_000_000, costUsd: 0.9, startedAt: T0 - 600_000,
  rateLimits: [
    { kind: 'five_hour', percentUsed: 3.5, resetsAt: '2026-10-09T22:00:00.000Z' },
    { kind: 'seven_day', percentUsed: 22, resetsAt: '2026-10-14T10:00:00Z' },
  ],
  counters: withTtl(addTurn(EMPTY_COUNTERS, USAGE, T0 - 30_000), '1h'), ttl: '1h',
  git: { branch: 'feat/x', detached: false, uncommitted: 2, ahead: 1, hasUpstream: true },
  pr: { number: 102, url: 'https://github.com/o/r/pull/102', reviewState: 'approved' },
  proc: { pid: 22695, procStart: 'Sun Oct  4 22:57:51 2026' },
  ...over,
})

test('the payload is the status-line shape census reads, with a census_mod block (golden)', async () => {
  expect(buildPayload(snap(), T0, 'turn.complete')).toEqual({
    session_id: 's1',
    transcript_path: '/cfg/projects/-repo/s1.jsonl',
    cwd: '/repo',
    workspace: { current_dir: '/repo', project_dir: '/repo' },
    model: { id: 'claude-opus-5-5', display_name: 'Opus 5.5' },
    context_window: { used_percentage: 9, context_window_size: 1_000_000, total_input_tokens: 100, total_output_tokens: 100 },
    cost: { total_cost_usd: 0.9, total_duration_ms: 600_000 },
    rate_limits: {
      five_hour: { used_percentage: 3.5, resets_at: Date.parse('2026-10-09T22:00:00Z') / 1000 },
      seven_day: { used_percentage: 22, resets_at: Date.parse('2026-10-14T10:00:00Z') / 1000 },
    },
    prompt_cache: {
      warm: true, ttl: '1h', requests: 1, expires_at: (T0 - 30_000 + 3_600_000) / 1000,
      hit_ratio: 90 / 100, session_hit_ratio: 90 / 100,
    },
    session_name: 'census mod',
    pr: { number: 102, url: 'https://github.com/o/r/pull/102', review_state: 'approved' },
    version: '2.1.289',
    census_mod: { version: 1, pid: 22695, proc_start: 'Sun Oct  4 22:57:51 2026', event: 'turn.complete' },
  })
})

test('rate limits become census windows: epoch SECONDS and a percent, or the window is left out', async () => {
  expect(rateLimitsOf([{ kind: 'five_hour', percentUsed: 41.7, resetsAt: '2026-10-09T22:00:00Z' }])).toEqual({
    five_hour: { used_percentage: 41.7, resets_at: 1_791_583_200 },
  })
  expect(rateLimitsOf([{ kind: 'five_hour', percentUsed: 1 }, { kind: 'seven_day', percentUsed: 1, resetsAt: 'garbage' }])).toEqual({})
})

test('what cannot be known is omitted or null, never faked; a worktree and a clean exit are marked', async () => {
  const p = buildPayload(
    snap({ ctxPct: null, ctxWindow: null, costUsd: null, startedAt: null, rateLimits: [], model: null, sessionName: null, pr: null, version: null, proc: null, transcriptPath: null, worktreePath: '/wt', counters: EMPTY_COUNTERS }),
    T0, 'session.end', 'prompt_input_exit',
  )

  expect(p.context_window).toEqual({ used_percentage: null, total_input_tokens: 0, total_output_tokens: 0 })
  expect(p.cost).toEqual({})
  expect(p).not.toHaveProperty('rate_limits')
  expect(p).not.toHaveProperty('model')
  expect(p).not.toHaveProperty('pr')
  expect(p).not.toHaveProperty('transcript_path')
  expect(p.worktree).toEqual({ path: '/wt' })
  expect(p.prompt_cache).toEqual({ warm: false, ttl: '1h', requests: 0 })
  expect(p.census_mod).toEqual({ version: 1, event: 'session.end', ended: 'prompt_input_exit' })
})

test('a PR with no review decision carries no review_state; a compaction makes the cache cold', async () => {
  const p = buildPayload(snap({ pr: { number: 3, url: 'u' }, counters: compacted(snap().counters, T0) }), T0, 'compact')

  expect(p.pr).toEqual({ number: 3, url: 'u' })
  expect((p.prompt_cache as { warm: boolean }).warm).toBe(false)
})

test('model ids become display names the way the status line spells them', async () => {
  expect(modelOf('claude-opus-5-5[1m]')).toEqual({ id: 'claude-opus-5-5', display_name: 'Opus 5.5' })
  expect(modelOf('claude-haiku-4-5-20251001')).toEqual({ id: 'claude-haiku-4-5-20251001', display_name: 'Haiku 4.5' })
  expect(modelOf('something-else')).toEqual({ id: 'something-else', display_name: 'something-else' })
})
