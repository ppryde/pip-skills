import { describe, expect, test } from 'claude-code/testing'
import { checkOverrides, formatOverride, fromModelThresholds, formatWindow, overridesJson, modelMatches, modelTokens, ordered, parseKey, parseOverridesArgs, parseWindow, patternFor, removeOverride, resolve, setOverride, validPattern } from '../plugin/core/overrides'
import type { Override } from '../plugin/types'

const M = 1_000_000
const OPUS55 = 'claude-opus-5-5[1m]'
const BASE = { nudgeAt: 35, step: 5, lastLightAt: 25 }

describe('models', () => {
  test('ids, display names and shorthand come to the same tokens', () => {
    expect(modelTokens(OPUS55)).toEqual(['opus', '5', '5', '1', 'm'])
    expect(modelTokens('Opus 5.5 (1M context)')).toEqual(['opus', '5', '5', '1', 'm', 'context'])
    expect(modelTokens('opus5.5')).toEqual(['opus', '5', '5'])
  })
  test('a family takes every model in it; a version only that version', () => {
    expect(modelMatches('opus', OPUS55)).toBe(true)
    expect(modelMatches('opus', 'claude-sonnet-5-5')).toBe(false)
    expect(modelMatches('opus5.5', OPUS55)).toBe(true)
    expect(modelMatches('opus-5-5', 'Opus 5.5 (1M context)')).toBe(true)
    expect(modelMatches('opus5.5', 'claude-opus-4-5-20251101')).toBe(false)
    expect(modelMatches('opus5', OPUS55)).toBe(true)
  })
  test('tokens match whole, not as text prefixes', () => expect(modelMatches('opus5', 'claude-opus-55')).toBe(false))
  test('a pattern is a family and at most major.minor', () => {
    for (const ok of ['opus', 'opus5', 'opus5.5', 'opus-5-5', 'claude-opus-5-5']) expect(validPattern(ok)).toBe(true)
    for (const bad of ['', '--', '5.5', 'opus-4-5-20251101', 'opus 5 5 1']) expect(validPattern(bad)).toBe(false)
  })
  test('the pattern for a model names its version, never its snapshot or window', () => {
    expect(patternFor(OPUS55)).toBe('opus5.5')
    expect(patternFor('claude-haiku-4-5-20251001')).toBe('haiku4.5')
    expect(patternFor('Opus 5.5 (1M context)')).toBe('opus5.5')
    expect(patternFor('opus')).toBe('opus')
  })
})

describe('resolve', () => {
  const overrides: Override[] = [
    { window: M, nudgeAt: 40, step: 10 },
    { model: 'opus', nudgeAt: 30, lastLightAt: 50 },
    { model: 'opus', window: M, nudgeAt: 25 },
    { model: 'opus5.5', window: M, nudgeAt: 20 },
    { model: 'opus5.5', nudgeAt: 28 },
    { window: 200_000, nudgeAt: 70 },
  ]
  const at = (model: string | null, window: number | null) => resolve(BASE, overrides, model, window).values
  test('model and window, the longer pattern first', () => {
    expect(at(OPUS55, M).nudgeAt).toBe(20)
    expect(at('claude-opus-4-5', M).nudgeAt).toBe(25)
  })
  test('model and window beat a more specific model alone', () =>
    expect(resolve(BASE, [{ model: 'opus5.5', nudgeAt: 28 }, { model: 'opus', window: M, nudgeAt: 25 }], OPUS55, M).values.nudgeAt).toBe(25))
  test('window beats model', () => expect(resolve(BASE, [{ model: 'opus', nudgeAt: 30 }, { window: M, nudgeAt: 40 }], OPUS55, M).values.nudgeAt).toBe(40))
  test('field by field: each value from the most specific override that sets it', () => {
    const v = resolve(BASE, overrides, OPUS55, M)
    expect(v.values).toEqual({ nudgeAt: 20, step: 10, lastLightAt: 50 })
    expect(v.from.nudgeAt).toEqual({ model: 'opus5.5', window: M, nudgeAt: 20 })
    expect(v.from.step).toEqual({ window: M, nudgeAt: 40, step: 10 })
    expect(v.from.lastLightAt).toEqual({ model: 'opus', nudgeAt: 30, lastLightAt: 50 })
  })
  test('a model override covers every window of that model', () => {
    expect(at(OPUS55, 200_000).nudgeAt).toBe(70)
    expect(at(OPUS55, 500_000).nudgeAt).toBe(28)
    expect(at('claude-opus-4-5', 500_000).nudgeAt).toBe(30)
  })
  test('nothing matches: the settings', () => {
    expect(at('claude-haiku-4-5', 500_000)).toEqual(BASE)
    expect(resolve(BASE, overrides, 'x', 500_000).from).toEqual({})
  })
  test('model unknown: only window overrides; window unknown: only model overrides', () => {
    expect(at(null, M).nudgeAt).toBe(40)
    expect(at(OPUS55, null).nudgeAt).toBe(28)
  })
  test('ambiguous: a window override and a model override set the same field and nothing with both keys settles it', () => {
    const l: Override[] = [{ window: M, nudgeAt: 40, step: 10 }, { model: 'opus', nudgeAt: 30, lastLightAt: 50 }]
    expect(resolve(BASE, l, OPUS55, M).ambiguous).toEqual({ model: l[1], window: l[0], fields: ['nudgeAt'] })
    expect(resolve(BASE, [...l, { model: 'opus', window: M, nudgeAt: 25 }], OPUS55, M).ambiguous).toBe(null)
    expect(resolve(BASE, [{ window: M, step: 10 }, { model: 'opus', nudgeAt: 30 }], OPUS55, M).ambiguous).toBe(null)
    expect(resolve(BASE, l, OPUS55, 200_000).ambiguous).toBe(null)
  })
})

describe('editing the overrides', () => {
  test('set replaces the override with the same key, whatever the spelling', () => {
    expect(setOverride([{ model: 'opus5.5', nudgeAt: 28 }, { window: M, nudgeAt: 40 }], { model: 'opus-5-5', nudgeAt: 22 }))
      .toEqual([{ window: M, nudgeAt: 40 }, { model: 'opus-5-5', nudgeAt: 22 }])
  })
  test('a model override and a model+window override are different keys', () =>
    expect(setOverride([{ model: 'opus', nudgeAt: 30 }], { model: 'opus', window: M, nudgeAt: 25 })).toHaveLength(2))
  test('rm takes out only the exact key', () => {
    const l: Override[] = [{ model: 'opus', nudgeAt: 30 }, { model: 'opus', window: M, nudgeAt: 25 }]
    expect(removeOverride(l, { model: 'opus' })).toEqual({ overrides: [{ model: 'opus', window: M, nudgeAt: 25 }], removed: true })
    expect(removeOverride(l, { window: M }).removed).toBe(false)
  })
  test('ordered lists the overrides in the order they are tried', () => {
    const l: Override[] = [{ model: 'opus', nudgeAt: 30 }, { window: M, nudgeAt: 40, step: 10 }, { model: 'opus', window: M, nudgeAt: 25 }]
    expect(ordered(l).map(formatOverride)).toEqual(['model=opus window=1M → nudge 25%', 'window=1M → nudge 40%, step 10%', 'model=opus → nudge 30%'])
  })
})

describe('checkOverrides', () => {
  test('a good file round-trips', () => {
    const overrides: Override[] = [{ window: 200_000, nudgeAt: 70 }, { model: 'opus5.5', window: M, nudgeAt: 20, step: 10, lastLightAt: 40 }]
    expect(checkOverrides(overridesJson(overrides))).toEqual({ overrides, faults: [] })
  })
  test('broken JSON or the wrong shape: no overrides, one fault', () => {
    expect(checkOverrides('{ overrides: ').faults[0]).toContain('not valid JSON')
    expect(checkOverrides('[]')).toEqual({ overrides: [], faults: ['expected { "overrides": [ … ] }'], fileFault: true })
    expect(checkOverrides('{ overrides: ').fileFault).toBe(true)
    expect(checkOverrides('{ "overrides": [{ "window": "1m", "nudgeAt": 50 }] }').fileFault).toBeUndefined()
  })
  test('each fault drops only its override and says why', () => {
    const r = checkOverrides(JSON.stringify({ overrides: [
      { window: M, nudgeAt: 40 },
      { nudgeAt: 50 },
      { model: 'opus-4-5-20251101', nudgeAt: 30 },
      { window: '1m', nudgeAt: 30 },
      { window: M, nudgeat: 30 },
      { model: 'opus', nudgeAt: 150 },
      { model: 'opus', step: 0 },
      { model: 'opus' },
      { window: 1_000_000, nudgeAt: 45 },
      'junk',
    ] }))
    expect(r.overrides).toEqual([{ window: M, nudgeAt: 40 }])
    expect(r.faults).toEqual([
      'override 2: needs a model, a window or both',
      'override 3: model must be a family and optional version, like "opus" or "opus5.5"',
      'override 4: window must be a whole number of tokens, like 1000000',
      'override 5: unknown key "nudgeat" (allowed: model, window, nudgeAt, step, lastLightAt)',
      'override 6: nudgeAt must be a whole % from 1 to 100',
      'override 7: step must be a whole % from 1 to 50',
      'override 8: sets nothing (give it nudgeAt, step, lastLightAt or any of them)',
      'override 9: same key as an earlier override (window=1M); the earlier one stands',
      'override 10: not an object',
    ])
  })
})

describe('parsing', () => {
  test('windows', () => {
    expect(parseWindow('1m')).toBe(M)
    expect(parseWindow('200K')).toBe(200_000)
    expect(parseWindow('1000000')).toBe(M)
    expect(parseWindow('big')).toBe(null)
    expect(formatWindow(M)).toBe('1M')
    expect(formatWindow(200_000)).toBe('200k')
  })
  test('keys', () => {
    expect(parseKey('model=opus5.5 window=1m')).toEqual({ model: 'opus5.5', window: M })
    expect(parseKey('window=200k')).toEqual({ window: 200_000 })
    for (const bad of ['', 'opus', 'model=opus model=haiku', 'window=huge', 'colour=red']) expect(parseKey(bad)).toBe(null)
  })
  test('commands', () => {
    expect(parseOverridesArgs('')).toEqual({ op: 'list' })
    expect(parseOverridesArgs('check')).toEqual({ op: 'list' })
    expect(parseOverridesArgs('add')).toEqual({ op: 'add' })
    expect(parseOverridesArgs('rm model=opus window=1m')).toEqual({ op: 'rm', key: { model: 'opus', window: M } })
    for (const bad of ['rm', 'rm 20', 'add model=opus', 'set model=opus 20', 'bogus']) expect(parseOverridesArgs(bad)).toEqual({ op: 'error' })
  })
})

describe('parseWindow refuses counts that are not whole', () => {
  test('1.4 is not window=1, but float noise in 1.1m is fine', () => {
    expect(parseWindow('1.4')).toBe(null)
    expect(parseWindow('1.0005k')).toBe(null)
    expect(parseWindow('1.1m')).toBe(1_100_000)
    expect(parseWindow('1.5k')).toBe(1_500)
    expect(parseKey('window=1.4')).toBe(null)
  })
})

describe('fromModelThresholds (0.1.3 store overrides)', () => {
  test('[1m] becomes a window, a family a model, both together a model+window', () => {
    expect(fromModelThresholds({ modelThresholds: {
      '[1m]': { nudgeAt: 50 }, haiku: { nudgeAt: 25, lastLightAt: 40 }, 'opus-5-5[1m]': { lastLightAt: 30 },
    } })).toEqual({ overrides: [
      { model: 'opus5.5', window: 1_000_000, lastLightAt: 30 }, { model: 'haiku', nudgeAt: 25, lastLightAt: 40 }, { window: 1_000_000, nudgeAt: 50 },
    ], dropped: [] })
  })
  test('a pattern this format cannot say, or one with nothing valid, is dropped by name', () => {
    expect(fromModelThresholds({ modelThresholds: { '5-5]': { nudgeAt: 55 }, opus: { nudgeAt: 40.5 } } }))
      .toEqual({ overrides: [], dropped: ['5-5] (no equivalent)', 'opus (sets nothing)'] })
    expect(fromModelThresholds({ nudgeAt: 35 })).toEqual({ overrides: [], dropped: [] })
    expect(fromModelThresholds(null)).toEqual({ overrides: [], dropped: [] })
  })
})

test('fromModelThresholds: two keys that collapse to one keep 0.1.3\'s winner, the longer pattern', () => {
  expect(fromModelThresholds({ modelThresholds: { opus: { nudgeAt: 40 }, 'claude-opus': { nudgeAt: 60 } } }))
    .toEqual({ overrides: [{ model: 'opus', nudgeAt: 60 }], dropped: ['opus (model=opus from a longer pattern won)'] })
})
