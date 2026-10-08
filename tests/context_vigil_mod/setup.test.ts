import { describe, expect, test } from 'claude-code/testing'
import { DEFAULTS } from '../../plugins/context-vigil-mod/core/settings'
import { ALIASES, FLOW, STEPS, TELL, applyAnswers, extractAnswers, isStep, nextCard, questionFor, stepForQuestion } from '../../plugins/context-vigil-mod/core/setup'
import type { StepId } from '../../plugins/context-vigil-mod/types'

const ALL = Object.keys(STEPS) as StepId[]

describe('cards fit AskUserQuestion', () => {
  test('headers ≤ 12 UTF-16 units; 2–4 options including Tell me more', () => {
    for (const id of ALL) {
      const q = questionFor(id)
      expect(q.header.length).toBeLessThanOrEqual(12)
      expect(q.options.length).toBeGreaterThanOrEqual(2)
      expect(q.options.length).toBeLessThanOrEqual(4)
      expect(q.options.at(-1)?.label).toBe(TELL)
      expect(q.question.endsWith('?')).toBe(true)
    }
  })
  test('Tell me more re-asks the same question with the explanation first', () => {
    const q = questionFor('bar', true)
    expect(q.question.startsWith(STEPS.bar.explain)).toBe(true)
    expect(q.question.endsWith(STEPS.bar.question)).toBe(true)
    expect(stepForQuestion(q.question)).toBe('bar')
    expect(stepForQuestion(STEPS.bar.question)).toBe('bar')
    expect(stepForQuestion('something else?')).toBe(undefined)
  })
  test('last light says it needs a 1-hour cache and stays off for a 5-minute one', () => {
    const t = STEPS.last_light.explain
    expect(t).toContain('1-hour prompt cache')
    expect(t).toContain('5-minute')
  })
  test('the copy says why, in the owner-approved words', () => {
    expect(STEPS.nudge.question).toBe('Big contexts get slower and pricier. At what % should I suggest a handover?')
    expect(STEPS.nudge.explain).not.toMatch(/phone/i)
    expect(STEPS.bar.question).toBe("Show a one-line bar above the prompt when it's time to hand over?")
    expect(STEPS.bar.explain).toContain('Off = a notice line instead')
    expect(STEPS.auto.question).toBe("While you're away and I'm still working, may I hand over, clear and carry on by myself?")
    expect(STEPS.idle.question).toBe('Auto handovers pause while you\'re interacting. How long without a message from you before I treat the session as unattended?')
    expect(STEPS.idle.options.map(o => o.description)).toEqual(['You step away properly when you leave', 'Recommended', 'You flit between windows and come back later'])
    expect(STEPS.last_light.question).toBe('When we\'re both idle, write a handover just before the 1-hour cache expires, so coming back is cheap?')
    expect(STEPS.last_light.explain).toContain('Works only with a 1-hour prompt cache')
    expect(STEPS.last_light_at.question).toBe('Only bother when context is at least…?')
    expect(STEPS.limits.question).toBe('Near a 7-day or spend limit, stop early with a handover so no work is lost?')
    expect(STEPS.limit_pct.question).toBe('Stop at what % of the limit?')
    expect(STEPS.limit_windows.options.map(o => o.label)).toEqual(['Weekly (seven_day)', 'Spend cap (spend_limit)'])
    expect(STEPS.rc.question).toBe("I can't see you typing on the phone, so a clear could land mid-message. Allow auto-clear in phone sessions?")
    expect(STEPS.rc.explain).toContain('30-second countdown')
  })
  test('no header has an emoji glued to its first letter', () => {
    for (const id of Object.keys(STEPS) as StepId[]) expect(STEPS[id].header).not.toMatch(/\uFE0F[A-Za-z]/)
  })
  test('window labels map back to their values', () => {
    expect(applyAnswers(DEFAULTS, [{ step: 'limit_windows', answer: 'Spend cap (spend_limit)' }]).settings.limitWindows).toEqual(['spend_limit'])
    expect(applyAnswers(DEFAULTS, [{ step: 'limit_windows', answer: 'Spend cap (spend_limit), Weekly (seven_day)' }]).settings.limitWindows).toEqual(['seven_day', 'spend_limit'])
  })
  test('windows is multi-select', () => expect(questionFor('limit_windows').multiSelect).toBe(true))
})

describe('nextCard', () => {
  test('defaults: card 1 skips steps whose parent is off', () => {
    expect(nextCard(DEFAULTS, [])).toEqual(['nudge', 'bar', 'auto', 'last_light'])
  })
  test('card 2 picks up follow-ups the answers switched on, never a dependant beside its parent', () => {
    const s = { ...DEFAULTS, auto: true, lastLight: true }
    expect(nextCard(s, ['nudge', 'bar', 'auto', 'last_light'])).toEqual(['idle', 'last_light_at', 'limits'])
  })
  test('card 3 asks the limits follow-ups only after limits was answered On', () => {
    const asked = ['nudge', 'bar', 'auto', 'last_light', 'idle', 'last_light_at', 'limits'] as StepId[]
    expect(nextCard(DEFAULTS, asked)).toEqual(['limit_pct', 'limit_windows'])
    expect(nextCard({ ...DEFAULTS, limits: false }, asked)).toEqual([])
  })
  test('done when nothing is left', () => {
    expect(nextCard(DEFAULTS, [...FLOW])).toEqual([])
  })
  test('one step by alias; dependants follow in the next card', () => {
    expect(nextCard(DEFAULTS, [], 'bar')).toEqual(['bar'])
    expect(nextCard(DEFAULTS, [], 'limits')).toEqual(['limits'])
    expect(nextCard(DEFAULTS, ['limits'], 'limits')).toEqual(['limit_pct', 'limit_windows'])
    expect(nextCard({ ...DEFAULTS, auto: false }, [], 'auto')).toEqual(['auto'])
    expect(nextCard({ ...DEFAULTS, auto: false }, ['auto'], 'auto')).toEqual([])
    expect(nextCard(DEFAULTS, [], 'rc')).toEqual(['rc'])
    expect(nextCard(DEFAULTS, [], 'bogus')).toEqual([])
    expect(ALIASES['last-light']).toEqual(['last_light', 'last_light_at'])
  })
  test('isStep tells a known alias from a typo', () => {
    expect(isStep('limits')).toBe(true)
    expect(isStep('bogus')).toBe(false)
    expect(isStep('toString')).toBe(false)
    expect(isStep('constructor')).toBe(false)
    expect(nextCard(DEFAULTS, [], 'toString')).toEqual([])
    expect(nextCard(DEFAULTS, [], '__proto__')).toEqual([])
  })
})

describe('extractAnswers', () => {
  test('answers on the tool input win', () => {
    expect(extractAnswers({ answers: { 'Q?': 'A' } }, { result: { answers: { 'Q?': 'B' } } })).toEqual({ 'Q?': 'A' })
  })
  test('else answers on the tool result', () => {
    expect(extractAnswers({}, { result: { questions: [], answers: { 'Q?': 'B' } } })).toEqual({ 'Q?': 'B' })
  })
  test('non-string answers are dropped; nothing found is empty', () => {
    expect(extractAnswers({ answers: { 'Q?': 3, 'R?': 'x' } }, undefined)).toEqual({ 'R?': 'x' })
    expect(extractAnswers(null, { deny: 'dismissed' })).toEqual({})
  })
})

describe('applyAnswers', () => {
  test('labels apply', () => {
    const r = applyAnswers(DEFAULTS, [
      { step: 'nudge', answer: '25%' }, { step: 'bar', answer: 'Off' }, { step: 'auto', answer: 'On' }, { step: 'idle', answer: '60 min' },
      { step: 'last_light', answer: 'On' }, { step: 'last_light_at', answer: '50%' }, { step: 'limits', answer: 'Off' }, { step: 'rc', answer: 'Yes' },
    ])
    expect(r.retell).toEqual([])
    expect(r.settings).toEqual({ ...DEFAULTS, nudgeAt: 25, bar: false, auto: true, idleMin: 60, lastLight: true, lastLightAt: 50, limits: false, rcAutoClear: 'yes' })
  })
  test('Tell me more is collected for a retell and changes nothing', () => {
    const r = applyAnswers(DEFAULTS, [{ step: 'bar', answer: TELL }, { step: 'nudge', answer: '50%' }])
    expect(r.retell).toEqual(['bar'])
    expect(r.settings).toEqual({ ...DEFAULTS, nudgeAt: 50 })
  })
  test('trigger % takes Other as a number 1–100', () => {
    expect(applyAnswers(DEFAULTS, [{ step: 'limit_pct', answer: '97' }]).settings.limitPct).toBe(97)
    expect(applyAnswers(DEFAULTS, [{ step: 'limit_pct', answer: '95% (Recommended)' }]).settings.limitPct).toBe(95)
    const bad = applyAnswers(DEFAULTS, [{ step: 'limit_pct', answer: 'lots' }])
    expect(bad.retell).toEqual(['limit_pct'])
    expect(bad.settings.limitPct).toBe(95)
  })
  test('windows multi-select, comma-joined, any order; empty is re-asked', () => {
    expect(applyAnswers(DEFAULTS, [{ step: 'limit_windows', answer: 'spend_limit' }]).settings.limitWindows).toEqual(['spend_limit'])
    expect(applyAnswers(DEFAULTS, [{ step: 'limit_windows', answer: 'spend_limit, seven_day' }]).settings.limitWindows).toEqual(['seven_day', 'spend_limit'])
    expect(applyAnswers(DEFAULTS, [{ step: 'limit_windows', answer: `seven_day, ${TELL}` }]).retell).toEqual(['limit_windows'])
    // R1-23: an empty selection is re-asked, never stored as "watch nothing"
    const empty = applyAnswers(DEFAULTS, [{ step: 'limit_windows', answer: '' }])
    expect(empty.retell).toEqual(['limit_windows'])
    expect(empty.settings.limitWindows).toEqual(DEFAULTS.limitWindows)
  })
  test('an unknown label is retold', () => {
    expect(applyAnswers(DEFAULTS, [{ step: 'bar', answer: 'Maybe' }]).retell).toEqual(['bar'])
  })
})
