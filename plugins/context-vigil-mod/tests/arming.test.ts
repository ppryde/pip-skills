import { describe, expect, test } from 'claude-code/testing'
import { EMPTY_ACTIVITY, WORKING_MS, armed, classifyOrigin, mode, onPhone, record, transition } from '../core/arming'

const MIN = 60_000
const S = { idleMin: 30, auto: true }

describe('classifyOrigin', () => {
  test('people', () => {
    for (const k of ['composer', 'bridge', 'slack-ping']) expect(classifyOrigin(k)).toBe('human')
  })
  test('headless', () => expect(classifyOrigin('sdk')).toBe('headless'))
  test('the agent working on its own', () => {
    for (const k of ['task-notification', 'scheduled-trigger', 'peer', 'peer-send-message', 'coordinator', 'observer', 'plugin', 'auto-continuation', 'unclassified', 'channel']) {
      expect(classifyOrigin(k)).toBe('agent')
    }
  })
})

describe('record', () => {
  test('a human prompt stamps time and origin; bridge also stamps lastBridgeAt', () => {
    const a = record(EMPTY_ACTIVITY, { kind: 'prompt', origin: 'bridge', at: 5 })
    expect(a).toEqual({ ...EMPTY_ACTIVITY, lastHumanAt: 5, lastHumanOrigin: 'bridge', lastBridgeAt: 5 })
  })
  test('an agent prompt is agent activity', () => {
    expect(record(EMPTY_ACTIVITY, { kind: 'prompt', origin: 'task-notification', at: 7 }).lastAgentAt).toBe(7)
  })
  test('sdk marks the session headless', () => {
    const a = record(EMPTY_ACTIVITY, { kind: 'prompt', origin: 'sdk', at: 1 })
    expect(a.headless).toBe(true)
    expect(a.lastAgentAt).toBe(1)
  })
  test('edits and human commands keep the last origin', () => {
    const a = record(record(EMPTY_ACTIVITY, { kind: 'prompt', origin: 'composer', at: 1 }), { kind: 'edit', at: 9 })
    expect(a.lastHumanAt).toBe(9)
    expect(a.lastHumanOrigin).toBe('composer')
    expect(record(a, { kind: 'human-command', at: 11 }).lastHumanAt).toBe(11)
  })
  test('agent steps', () => expect(record(EMPTY_ACTIVITY, { kind: 'agent-step', at: 3 }).lastAgentAt).toBe(3))
})

describe('mode', () => {
  const human = (at: number) => record(EMPTY_ACTIVITY, { kind: 'prompt', origin: 'composer', at })
  test('engaged within the idle window is attended, whatever the agent does', () => {
    const a = record(human(0), { kind: 'agent-step', at: 10 * MIN })
    expect(mode(a, 10 * MIN, S)).toBe('attended')
  })
  test('idle past the window with the agent working is auto', () => {
    const a = record(human(0), { kind: 'agent-step', at: 31 * MIN })
    expect(mode(a, 31 * MIN, S)).toBe('auto')
  })
  test('the agent counts as working for 2 minutes only', () => {
    const a = record(human(0), { kind: 'agent-step', at: 31 * MIN })
    expect(mode(a, 31 * MIN + WORKING_MS - 1, S)).toBe('auto')
    expect(mode(a, 31 * MIN + WORKING_MS, S)).toBe('idle')
  })
  test('both idle is idle', () => expect(mode(human(0), 40 * MIN, S)).toBe('idle'))
  test('headless is never attended', () => {
    const a = record(record(EMPTY_ACTIVITY, { kind: 'prompt', origin: 'sdk', at: 0 }), { kind: 'edit', at: 1 })
    expect(mode(a, 2, S)).toBe('auto')
  })
  test('armed needs auto mode switched on', () => {
    const a = record(human(0), { kind: 'agent-step', at: 31 * MIN })
    expect(armed(a, 31 * MIN, S)).toBe(true)
    expect(armed(a, 31 * MIN, { ...S, auto: false })).toBe(false)
  })
})

test('transition', () => {
  expect(transition('attended', 'auto')).toBe('arm')
  expect(transition('idle', 'auto')).toBe('arm')
  expect(transition('auto', 'attended')).toBe('disarm')
  expect(transition('auto', 'idle')).toBe('disarm')
  expect(transition('attended', 'idle')).toBe(null)
  expect(transition('auto', 'auto')).toBe(null)
})

test('onPhone follows the last human origin', () => {
  expect(onPhone(record(EMPTY_ACTIVITY, { kind: 'prompt', origin: 'bridge', at: 1 }))).toBe(true)
  expect(onPhone(record(EMPTY_ACTIVITY, { kind: 'prompt', origin: 'composer', at: 1 }))).toBe(false)
  expect(onPhone(EMPTY_ACTIVITY)).toBe(false)
})
