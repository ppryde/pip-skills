import { expect, test } from 'claude-code/testing'
import { V } from '../core/voice'

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
  const samples = [
    V.nudge(41), V.handoverSaved('/x.md'), V.handoverUnrequested('/x.md'), V.deferredDropped, V.handoverInterrupted, V.resumeStale('/x.md'), V.resumeLatched('/x.md'), V.handoverFailed, V.clearRejected, V.countdownLine(30),
    V.countdownCancelled, V.setupUsage, V.rcAsk, V.pendingOffer('/x.md'), V.waiting('draft'), V.lastLightReady,
    V.lastLightAsk, V.limitLatched('14:05'), V.limitCleared, V.earlyStop('seven_day', 95, '14:05'),
    V.classicActive, V.setupSaved, V.handingOver, V.settingUp, V.cmdHandover, V.cmdSetup, V.renameFailed,
    V.resumeFailed('/x.md', null), V.resumeFailed(null, 'hi'), V.heldForLastLight,
  ]
  for (const s of samples) expect(/^\p{Extended_Pictographic}/u.test(s)).toBe(true)
})
test('waiting explains every guard reason', () => {
  for (const r of ['draft', 'latched', 'classic', 'rc-unanswered', 'rc-declined', 'rc-holdback', 'countdown', 'countdown-start'] as const) {
    expect(V.waiting(r).length).toBeGreaterThan(5)
  }
})
test('a failed resume names the handover and keeps the held text', () => {
  expect(V.resumeFailed('/x.md', null)).toContain('/x.md')
  expect(V.resumeFailed('/x.md', 'morning!')).toContain('morning!')
})
