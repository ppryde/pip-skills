import { describe, expect, test } from 'claude-code/testing'
import { LEAD_MS, TTL_1H, fireAt, holdOnReturn, rearm, shouldFire } from '../core/last-light'

test('fireAt is last API activity + 1h − lead; only a known 1-hour cache fires', () => {
  expect(fireAt(1000, '1h')).toBe(1000 + TTL_1H - LEAD_MS)
  expect(fireAt(1000, '5m')).toBe(null)
  expect(fireAt(1000, 'unknown')).toBe(null)
})

describe('shouldFire', () => {
  const ok = { enabled: true, mode: 'idle' as const, contextPct: 30, threshold: 25, pending: false, latched: false, armed: true }
  test('fires when every condition holds', () => expect(shouldFire(ok)).toEqual({ fire: true }))
  test('each condition blocks with its reason', () => {
    expect(shouldFire({ ...ok, enabled: false })).toEqual({ fire: false, reason: 'off' })
    expect(shouldFire({ ...ok, mode: 'attended' })).toEqual({ fire: false, reason: 'not-idle' })
    expect(shouldFire({ ...ok, mode: 'auto' })).toEqual({ fire: false, reason: 'not-idle' })
    expect(shouldFire({ ...ok, contextPct: 24 })).toEqual({ fire: false, reason: 'small' })
    expect(shouldFire({ ...ok, contextPct: null })).toEqual({ fire: false, reason: 'small' })
    expect(shouldFire({ ...ok, pending: true })).toEqual({ fire: false, reason: 'pending' })
    expect(shouldFire({ ...ok, latched: true })).toEqual({ fire: false, reason: 'latched' })
    expect(shouldFire({ ...ok, armed: false })).toEqual({ fire: false, reason: 'disarmed' })
  })
})

test('loop guard: only a human prompt re-arms', () => {
  expect(rearm(false, 'composer')).toBe(true)
  expect(rearm(false, 'bridge')).toBe(true)
  expect(rearm(false, 'plugin')).toBe(false)
  expect(rearm(false, 'scheduled-trigger')).toBe(false)
  expect(rearm(true, 'plugin')).toBe(true)
})

describe('holdOnReturn', () => {
  const f = { pendingIsLastLight: true, origin: 'composer', now: 10, cacheExpiresAt: 5 }
  test('a human prompt after expiry with a last-light handover pending is held', () => expect(holdOnReturn(f)).toBe(true))
  test('not before expiry, not for agent prompts, not without a last-light handover', () => {
    expect(holdOnReturn({ ...f, now: 4 })).toBe(false)
    expect(holdOnReturn({ ...f, origin: 'plugin' })).toBe(false)
    expect(holdOnReturn({ ...f, pendingIsLastLight: false })).toBe(false)
    expect(holdOnReturn({ ...f, cacheExpiresAt: null })).toBe(false)
  })
})
