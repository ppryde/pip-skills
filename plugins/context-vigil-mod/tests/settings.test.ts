import { describe, expect, test } from 'claude-code/testing'
import { DEFAULTS, STORE_KEY, loadSettings, pendingKey } from '../plugin/core/settings'

test('store keys', () => {
  expect(STORE_KEY).toBe('settings')
  expect(pendingKey('s1')).toBe('pending:s1')
})

describe('loadSettings', () => {
  test('nothing stored gives the defaults', () => {
    expect(loadSettings(undefined)).toEqual(DEFAULTS)
    expect(loadSettings(null)).toEqual(DEFAULTS)
    expect(loadSettings('junk')).toEqual(DEFAULTS)
  })
  test('the spec defaults', () => {
    expect(DEFAULTS).toEqual({
      nudgeAt: 35, step: 5, bar: true, auto: false, idleMin: 30,
      lastLight: false, lastLightAt: 25, limits: true, limitPct: 95,
      limitWindows: ['seven_day', 'spend_limit'], rcAutoClear: 'unanswered',
    })
  })
  test('valid fields override, the rest stay default', () => {
    const s = loadSettings({ auto: true, idleMin: 60, limitPct: 90 })
    expect(s.auto).toBe(true)
    expect(s.idleMin).toBe(60)
    expect(s.limitPct).toBe(90)
    expect(s.nudgeAt).toBe(35)
  })
  test('invalid fields fall back field by field', () => {
    const s = loadSettings({ nudgeAt: 250, bar: 'yes', idleMin: -3, limitWindows: ['seven_day', 'bogus', 'seven_day'], rcAutoClear: 'maybe' })
    expect(s.nudgeAt).toBe(35)
    expect(s.bar).toBe(true)
    expect(s.idleMin).toBe(30)
    expect(s.limitWindows).toEqual(['seven_day'])
    expect(s.rcAutoClear).toBe('unanswered')
  })
  test('a windows list with nothing valid left keeps the defaults, not an empty watch', () => {
    expect(loadSettings({ limitWindows: [] }).limitWindows).toEqual(['seven_day', 'spend_limit'])
    expect(loadSettings({ limitWindows: ['bogus'] }).limitWindows).toEqual(['seven_day', 'spend_limit'])
  })
  test('the defaults object is never shared', () => {
    const s = loadSettings(undefined)
    s.limitWindows.push('spend_limit')
    expect(DEFAULTS.limitWindows).toEqual(['seven_day', 'spend_limit'])
  })
})

test('0.1.3 modelThresholds ride along untouched until they have moved, so a settings save keeps them', () => {
  const legacy = { '[1m]': { nudgeAt: 50 } }
  const s = loadSettings({ nudgeAt: 40, modelThresholds: legacy })
  expect(s.modelThresholds).toEqual(legacy)
  expect(JSON.parse(JSON.stringify({ ...s, bar: false })).modelThresholds).toEqual(legacy)
  expect('modelThresholds' in loadSettings({ nudgeAt: 40 })).toBe(false)
})
