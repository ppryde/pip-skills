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

test('RC countdown: the band counts down each second', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true, rcAutoClear: 'yes' } } })
  await countdownSession($, w)
  const ui = await $.ui.mount(BAND())
  expect(await ui.find({ type: 'Text', text: /Handing over in 30 s/ })).toBeDefined()
  await w.clock.advance(3000)
  expect(await ui.find({ type: 'Text', text: /Handing over in 27 s/ })).toBeDefined()
  await ui.unmount()
})

const OFFER = '📜 A handover is waiting (/cfg/context-vigil-mod/handovers/s1-1.md) — /clear to resume from it'

test('RC countdown: a hot reload mid-countdown never clears; the handover is offered instead', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true, rcAutoClear: 'yes' } } })
  await countdownSession($, w)
  w.notices.length = 0
  await $.session.start(START)          // the reload: same session, $.state kept, timers gone
  await w.clock.advance(60_000)
  expect(w.commands).not.toContain('clear')
  expect(w.notices).toContain(OFFER)
  expect(w.state.get('context-vigil-mod.countdownEndsAt')).toBeNull()
})

for (const rcAutoClear of ['no', 'unanswered'] as const) {
  test(`RC ${rcAutoClear}: a hot reload never runs the parked unattended clear; it offers the handover`, async ($, on) => {
    const w = world(on, { store: { settings: { auto: true, rcAutoClear } } })
    await countdownSession($, w)
    expect(w.commands).not.toContain('clear')
    w.notices.length = 0
    await $.session.start(START)
    await w.clock.advance(60_000)
    expect(w.commands).not.toContain('clear')
    expect(w.notices).toContain(OFFER)
  })
}

// The phone facts (last human origin, last bridge prompt) must survive a hot reload, or a later
// unattended clear skips the whole RC gate.
async function autoHandoverAfter($: Engine, w: World) {
  await w.clock.advance(31 * MIN)
  await $.tool.call({ tool: 'Bash', tool_use_id: 'b', command: 'ls' } as never)
  await $.session.measure(measure(36))
  await w.clock.settle()
  await $.tool.call({ tool: TOOL, tool_use_id: 'h', goal: 'G', state: 'S', next_step: 'N', session_name: 'Name' } as never)
  await w.clock.advance(60_000)
}

for (const rcAutoClear of ['no', 'unanswered'] as const) {
  test(`RC ${rcAutoClear}: a new unattended handover after a reload still meets the RC gate`, async ($, on) => {
    const w = world(on, { store: { settings: { auto: true, rcAutoClear } } })
    await $.session.start(START)
    await $.prompt.submit(human('go', 'bridge'))
    await $.session.start(START)          // the reload
    await autoHandoverAfter($, w)
    expect(w.submits.some(s => s.text.includes(TOOL))).toBe(true)
    expect(w.commands).not.toContain('clear')
  })

  test(`RC ${rcAutoClear}: a deferred handover drained by the latch at a reload still meets the RC gate`, async ($, on) => {
    const w = world(on, { now: 1_000_000, store: { settings: { auto: true, rcAutoClear }, latch: { kind: 'five_hour', resetsAtMs: 1_000_000 + 60 * MIN } } })
    await $.session.start(START)
    await $.prompt.submit(human('go', 'bridge'))
    await w.clock.advance(31 * MIN)
    await $.tool.call({ tool: 'Bash', tool_use_id: 'b', command: 'ls' } as never)
    await $.session.measure(measure(36))          // armed while latched: deferred
    await w.clock.settle()
    expect(w.state.get('context-vigil-mod.deferred')).toMatchObject({ reason: 'threshold' })
    await w.clock.advance(30 * MIN)               // past the reset
    await $.session.start(START)                  // the reload lifts the latch and drains it
    await w.clock.settle()
    expect(w.submits.some(s => s.text.includes(TOOL))).toBe(true)
    await $.tool.call({ tool: TOOL, tool_use_id: 'h', goal: 'G', state: 'S', next_step: 'N', session_name: 'Name' } as never)
    await w.clock.advance(60_000)
    expect(w.commands).not.toContain('clear')
  })
}

test('the phone facts cross a clear and a reload after it', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true, rcAutoClear: 'no' } } })
  await $.session.start(START)
  await $.prompt.submit(human('go', 'bridge'))
  w.sessionId.value = 's2'
  await $.classic.SessionStart({ source: 'clear' } as never)
  expect(w.state.get('context-vigil-mod.phoneFacts')).toMatchObject({ lastHumanOrigin: 'bridge' })
  await $.session.start(START)            // a reload in the new session
  await autoHandoverAfter($, w)
  expect(w.submits.some(s => s.text.includes(TOOL))).toBe(true)
  expect(w.commands).not.toContain('clear')
})
