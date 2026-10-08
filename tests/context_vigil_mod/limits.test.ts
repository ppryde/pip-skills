import { describe, expect, test } from 'claude-code/testing'
import { HOP_MS, earlyStopDue, formatHHMM, latchCleared, latchFromMeasure, latchFromStopFailure, nextHop } from '../../plugins/context-vigil-mod/core/limits'

const T = Date.UTC(2026, 9, 4, 12)
const iso = (ms: number) => new Date(ms).toISOString()

describe('latch', () => {
  test('a rate_limit StopFailure latches on the fullest window', () => {
    const l = latchFromStopFailure('rate_limit', [
      { kind: 'five_hour', percentUsed: 100, resetsAt: iso(T + 3600_000) },
      { kind: 'seven_day', percentUsed: 60, resetsAt: iso(T + 86400_000) },
    ], T)
    expect(l).toEqual({ kind: 'five_hour', resetsAtMs: T + 3600_000 })
  })
  test('other errors never latch', () => expect(latchFromStopFailure('overloaded', [], T)).toBe(null))
  test('rate_limit with no window known latches for an hour', () => {
    expect(latchFromStopFailure('rate_limit', [], T)).toEqual({ kind: 'unknown', resetsAtMs: T + 3600_000 })
  })
  test('a measure at or past 100% latches', () => {
    expect(latchFromMeasure([{ kind: 'seven_day', percentUsed: 100, resetsAt: iso(T + 5) }])).toEqual({ kind: 'seven_day', resetsAtMs: T + 5 })
    expect(latchFromMeasure([{ kind: 'seven_day', percentUsed: 99.9, resetsAt: iso(T + 5) }])).toBe(null)
  })
  test('the latch clears at resetsAt or when its window drops', () => {
    const l = { kind: 'five_hour', resetsAtMs: T + 100 }
    expect(latchCleared(l, T, [{ kind: 'five_hour', percentUsed: 100 }])).toBe(false)
    expect(latchCleared(l, T + 100, [])).toBe(true)
    expect(latchCleared(l, T, [{ kind: 'five_hour', percentUsed: 3 }])).toBe(true)
    expect(latchCleared(null, T, [])).toBe(false)
  })
})

describe('earlyStopDue', () => {
  const s = { limits: true, limitPct: 95, limitWindows: ['seven_day' as const, 'spend_limit' as const] }
  const seven = { kind: 'seven_day', percentUsed: 96, resetsAt: iso(T + 1000) }
  test('a watched window at the trigger is due once per window', () => {
    const due = earlyStopDue([seven], s, [])
    expect(due).toEqual({ kind: 'seven_day', key: `seven_day:${iso(T + 1000)}`, pct: 96, resetsAtMs: T + 1000 })
    expect(earlyStopDue([seven], s, [due?.key ?? ''])).toBe(null)
  })
  test('five_hour is never watched; unwatched windows are ignored', () => {
    expect(earlyStopDue([{ kind: 'five_hour', percentUsed: 99, resetsAt: iso(T) }], s, [])).toBe(null)
    expect(earlyStopDue([seven], { ...s, limitWindows: ['spend_limit'] }, [])).toBe(null)
  })
  test('limits off or below the trigger: nothing', () => {
    expect(earlyStopDue([seven], { ...s, limits: false }, [])).toBe(null)
    expect(earlyStopDue([seven], { ...s, limitPct: 98 }, [])).toBe(null)
  })
  test('a window with no resetsAt cannot be keyed and is skipped', () => {
    expect(earlyStopDue([{ kind: 'seven_day', percentUsed: 99 }], s, [])).toBe(null)
  })
})

test('nextHop waits in ≤ 1 h hops and hits 0 at the resume time', () => {
  expect(nextHop(0, 5 * HOP_MS)).toBe(HOP_MS)
  expect(nextHop(0, 1000)).toBe(1000)
  expect(nextHop(1000, 1000)).toBe(0)
  expect(nextHop(2000, 1000)).toBe(0)
})

test('formatHHMM is local hours and minutes', () => {
  expect(formatHHMM(new Date(2026, 9, 4, 14, 5).getTime())).toBe('14:05')
  expect(formatHHMM(new Date(2026, 9, 4, 9, 0).getTime())).toBe('09:00')
})
