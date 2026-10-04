import { expect, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import { START, human, world } from './world'
import type { World } from './world'

const MIN = 60_000
const TOOL = 'mcp__context-vigil-mod__vigil_handover'
const BAND = (hasSurvey = false) => ({ plugin: 'context-vigil-mod', surface: 'terminal' as const, component: 'AbovePrompt' as const, props: { hasSurvey, isWorking: false } as never })
const measure = (percent: number) => ({ context: { window: 1_000_000, percent }, rateLimits: [], changed: ['context'] as never })
const hotkey = (el: unknown) => (el as { props?: { hotkey?: string } } | undefined)?.props?.hotkey

test('no bar before the threshold; from the crossing it shows live % and the configured threshold', async ($, on) => {
  world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  let ui = await $.ui.mount(BAND())
  expect(await ui.find({ key: 'handover' })).toBeUndefined()
  await ui.unmount()
  await $.session.measure(measure(41))
  ui = await $.ui.mount(BAND())
  expect(await ui.find({ type: 'Text', text: /context 41% · threshold 35%/ })).toBeDefined()
  expect(await ui.find({ key: 'handover' })).toBeDefined()
  await ui.unmount()
})

test('1 starts the handover and hides the bar', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(36))
  const ui = await $.ui.mount(BAND())
  await ui.press({ key: 'handover' })
  await w.clock.settle()
  expect(w.submits.at(-1)?.text).toContain(TOOL)
  await ui.unmount()
  const again = await $.ui.mount(BAND())      // a mount is a snapshot; a fresh one shows the new state
  expect(await again.find({ key: 'handover' })).toBeUndefined()
  await again.unmount()
})

test('2 brings the bar back at the next step; 0 hides it silently until a clear', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(36))
  let ui = await $.ui.mount(BAND())
  await ui.press({ key: 'later' })
  await ui.unmount()
  ui = await $.ui.mount(BAND())
  expect(await ui.find({ key: 'handover' })).toBeUndefined()
  await ui.unmount()
  await $.session.measure(measure(41))
  ui = await $.ui.mount(BAND())
  expect(await ui.find({ key: 'handover' })).toBeDefined()
  await ui.press({ key: 'dismiss' })
  await ui.unmount()
  await $.session.measure(measure(46))
  ui = await $.ui.mount(BAND())
  expect(await ui.find({ key: 'handover' })).toBeUndefined()
  await ui.unmount()
  expect(w.state.get('context-vigil-mod.lastNudged')).toBe(45)
  expect(w.notices.some(n => n.includes('Context at'))).toBe(false)
})

test('yields to survey, returns after', async ($, on) => {
  world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(36))
  let ui = await $.ui.mount(BAND(true))
  expect(await ui.find({ key: 'handover' })).toBeUndefined()
  await ui.unmount()
  ui = await $.ui.mount(BAND(false))
  expect(await ui.find({ key: 'handover' })).toBeDefined()
  await ui.unmount()
})

test('hotkeys are 1 / 2 / 0', async ($, on) => {
  world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(36))
  const ui = await $.ui.mount(BAND())
  const keys = await Promise.all(['handover', 'later', 'dismiss'].map(k => ui.find({ key: k })))
  expect(keys.map(hotkey)).toEqual(['1', '2', '0'])
  await ui.unmount()
})

test('on the phone: a notice instead of the bar', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi', 'bridge'))
  await $.session.measure(measure(36))
  const ui = await $.ui.mount(BAND())
  expect(await ui.find({ key: 'handover' })).toBeUndefined()
  await ui.unmount()
  expect(w.notices).toContain('🕯️ Context at 36% — say "hand over" (or /vho) when you\'re ready 📜')
})

test('with the bar switched off: a notice instead of the bar, in the terminal too', async ($, on) => {
  const w = world(on, { store: { settings: { bar: false } } })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(36))
  const ui = await $.ui.mount(BAND())
  expect(await ui.find({ key: 'handover' })).toBeUndefined()
  await ui.unmount()
  expect(w.notices).toContain('🕯️ Context at 36% — say "hand over" (or /vho) when you\'re ready 📜')
})

// The Remote Control countdown: auto mode on, RC auto-clear allowed, last prompt from the phone.
async function countdownSession($: Engine, w: World) {
  await $.session.start(START)
  await $.prompt.submit(human('go', 'bridge'))
  await w.clock.advance(31 * MIN)
  await $.tool.call({ tool: 'Bash', tool_use_id: 'b', command: 'ls' } as never)
  await $.session.measure(measure(36))
  await w.clock.settle()
  await $.tool.call({ tool: TOOL, tool_use_id: 'h', goal: 'G', state: 'S', next_step: 'N', session_name: 'Name' } as never)
  await w.clock.settle()
}

test('RC countdown: shown on the bar with Cancel on 0; runs out into the clear', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true, rcAutoClear: 'yes' } } })
  await countdownSession($, w)
  expect(w.notices).toContain('🧹 Handing over in 30 s — send anything to cancel')
  const ui = await $.ui.mount(BAND())
  expect(await ui.find({ type: 'Text', text: /Handing over in \d+ s/ })).toBeDefined()
  expect(hotkey(await ui.find({ key: 'cancel' }))).toBe('0')
  await ui.unmount()
  expect(w.commands).not.toContain('clear')
  await w.clock.advance(30_000)
  expect(w.commands).toContain('clear')
})

test('RC countdown: Cancel stops the clear and keeps the handover', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true, rcAutoClear: 'yes' } } })
  await countdownSession($, w)
  const ui = await $.ui.mount(BAND())
  await ui.press({ key: 'cancel' })
  await ui.unmount()
  await w.clock.advance(60_000)
  expect(w.commands).not.toContain('clear')
  expect(w.notices).toContain('🧹 Handover countdown cancelled — the handover is saved; /clear to resume from it')
  expect(w.state.get('context-vigil-mod.pending')).toMatchObject({ reason: 'threshold' })
})

test('RC countdown: sending anything cancels it', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true, rcAutoClear: 'yes' } } })
  await countdownSession($, w)
  await $.prompt.submit(human('wait!', 'bridge'))
  await w.clock.advance(60_000)
  expect(w.commands).not.toContain('clear')
  expect(w.notices).toContain('🧹 Handover countdown cancelled — the handover is saved; /clear to resume from it')
})
