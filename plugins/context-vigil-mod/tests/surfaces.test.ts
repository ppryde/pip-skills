import { describe, expect, test } from 'claude-code/testing'
import { COUNTDOWN_MS, HOLDBACK_MS, RECHECK_MS, clearGate, needsRcQuestion } from '../core/surfaces'

const base = { now: 1_000_000, draft: '', onPhone: false, lastBridgeAt: null, rcAutoClear: 'unanswered' as const, latched: false, countdownEndsAt: null, classicActive: false, unattended: true }

describe('clearGate', () => {
  test('terminal, empty box: go', () => expect(clearGate(base)).toEqual({ go: true }))
  test('classic active wins over everything', () => {
    expect(clearGate({ ...base, classicActive: true, latched: true })).toEqual({ go: false, reason: 'classic', recheckMs: null })
  })
  test('the latch parks the clear until it lifts', () => {
    expect(clearGate({ ...base, latched: true })).toEqual({ go: false, reason: 'latched', recheckMs: null })
  })
  test('a draft in the terminal box waits and rechecks', () => {
    expect(clearGate({ ...base, draft: 'half a sen' })).toEqual({ go: false, reason: 'draft', recheckMs: RECHECK_MS })
    expect(clearGate({ ...base, draft: '   ' })).toEqual({ go: true })
  })
  describe('on the phone, unattended', () => {
    const phone = { ...base, onPhone: true, lastBridgeAt: 0 }
    test('unanswered or declined never clears', () => {
      expect(clearGate(phone)).toEqual({ go: false, reason: 'rc-unanswered', recheckMs: null })
      expect(clearGate({ ...phone, rcAutoClear: 'no' })).toEqual({ go: false, reason: 'rc-declined', recheckMs: null })
    })
    test('allowed: holdback within 2 min of the last bridge prompt', () => {
      const f = { ...phone, rcAutoClear: 'yes' as const, lastBridgeAt: base.now - 30_000 }
      expect(clearGate(f)).toEqual({ go: false, reason: 'rc-holdback', recheckMs: HOLDBACK_MS - 30_000 })
    })
    test('allowed: then the countdown starts, runs, and lets it go', () => {
      const f = { ...phone, rcAutoClear: 'yes' as const }
      expect(clearGate(f)).toEqual({ go: false, reason: 'countdown-start', recheckMs: COUNTDOWN_MS })
      expect(clearGate({ ...f, countdownEndsAt: base.now + 10_000 })).toEqual({ go: false, reason: 'countdown', recheckMs: 10_000 })
      expect(clearGate({ ...f, countdownEndsAt: base.now })).toEqual({ go: true })
    })
  })
  test('a clear the person asked for from the phone goes straight through', () => {
    expect(clearGate({ ...base, onPhone: true, unattended: false })).toEqual({ go: true })
  })
})

test('needsRcQuestion only when auto mode would arm on the phone with no answer yet', () => {
  expect(needsRcQuestion(true, 'unanswered', true)).toBe(true)
  expect(needsRcQuestion(true, 'no', true)).toBe(false)
  expect(needsRcQuestion(false, 'unanswered', true)).toBe(false)
  expect(needsRcQuestion(true, 'unanswered', false)).toBe(false)
})
