import { expect, test } from 'claude-code/testing'
import { V } from '../plugin/core/voice'

test('bar strings', () => {
  expect(V.barLine(41, 35, null)).toBe('🕯️ context 41% · threshold 35%')
  expect(V.barLine(41, 35, '14:05')).toBe('🕯️ context 41% · threshold 35% · ⏳ resumes 14:05')
  expect(V.barHandover).toBe('📜 Hand over now')
  expect(V.barLater(45)).toBe('⏰ Remind me at 45%')
  expect(V.barDismiss).toBe('✖ Dismiss')
  expect(V.countdownLine(12)).toBe('🧹 Handing over in 12 s — 0 or send anything to cancel')
  expect(V.cancel).toBe('✖ Cancel')
})
test('every user-facing string is emoji-led', () => {
  // Every entry of V, not a hand-kept sample: a new string is checked the day it is added.
  const strings = Object.entries(V).flatMap(([k, v]) => {
    if (k === 'waiting') return []   // per reason, below
    return [typeof v === 'function' ? (v as (...a: unknown[]) => string)(...Array(v.length).fill('x')) : v]
  })
  expect(strings.length).toBe(Object.keys(V).length - 1)
  for (const s of strings) expect(/^\p{Extended_Pictographic}/u.test(s)).toBe(true)
})
test('the last-light choices are emoji-led too', () => {
  expect(V.lastLightResume).toBe('📜 Resume from handover')
  expect(V.lastLightCarryOn).toBe('💬 Carry on')
})
test('waiting explains every guard reason by name', () => {
  const why: Record<Parameters<typeof V.waiting>[0], RegExp> = {
    'draft': /draft in your prompt box/,
    'latched': /usage limit is in force/,
    'classic': /classic context-vigil is active/,
    'rc-declined': /auto-clear is off for Remote Control/,
    'rc-holdback': /active on the phone a moment ago/,
    'countdown': /countdown running — send anything to cancel/,
    'countdown-start': /Handing over in 30 s — send anything to cancel/,
  }
  for (const [r, re] of Object.entries(why) as [Parameters<typeof V.waiting>[0], RegExp][]) {
    expect(/^\p{Extended_Pictographic}/u.test(V.waiting(r))).toBe(true)
    expect(V.waiting(r)).toMatch(re)
  }
  // No two reasons share a message.
  expect(new Set(Object.keys(why).map(r => V.waiting(r as never))).size).toBe(Object.keys(why).length)
})
test('a failed resume names the handover and keeps the held text', () => {
  expect(V.resumeFailed('/x.md', null)).toContain('/x.md')
  expect(V.resumeFailed('/x.md', 'morning!')).toContain('morning!')
})
