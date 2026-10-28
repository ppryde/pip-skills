import { expect, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import { START, human, turn, world, endInto } from './world'
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

test('a 200k window nudges at the default override, 70%', async ($, on) => {
  world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  const small = (percent: number) => ({ ...measure(percent), context: { window: 200_000, percent } })
  await $.session.measure(small(41))
  let ui = await $.ui.mount(BAND())
  expect(await ui.find({ key: 'handover' })).toBeUndefined()
  await ui.unmount()
  await $.session.measure(small(72))
  ui = await $.ui.mount(BAND())
  expect(await ui.find({ type: 'Text', text: /context 72% · threshold 70%/ })).toBeDefined()
  expect(await ui.find({ key: 'later', text: /75%/ })).toBeDefined()
  await ui.unmount()
})

const OVERRIDES = '/cfg/context-vigil-mod/overrides.json'
const overridesFile = (overrides: unknown[]) => ({ [OVERRIDES]: JSON.stringify({ overrides }) })
const voverrides = ($: Engine, args: string) => $.command.run({ command: 'vigil-overrides', args, origin: { kind: 'composer' } } as never) as Promise<{ text?: string }>

test('with no overrides.json the default is written, so the 200k override is there to see', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  expect(JSON.parse(w.files.get(OVERRIDES) ?? '{}')).toEqual({ overrides: [{ window: 200_000, nudgeAt: 70 }] })
})

test('overrides for the session model and window set the threshold and step, field by field', async ($, on) => {
  const w = world(on, { files: overridesFile([{ model: 'opus', window: 1_000_000, nudgeAt: 25 }, { window: 1_000_000, step: 10 }, { model: 'sonnet', nudgeAt: 60 }]) })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(26))
  let ui = await $.ui.mount(BAND())
  expect(await ui.find({ type: 'Text', text: /context 26% · threshold 25%/ })).toBeDefined()
  expect(await ui.find({ key: 'later', text: /35%/ })).toBeDefined()
  await ui.unmount()
  w.model.value = 'claude-sonnet-5-5[1m]'
  await $.session.measure(measure(61))
  ui = await $.ui.mount(BAND())
  expect(await ui.find({ type: 'Text', text: /threshold 60%/ })).toBeDefined()
  await ui.unmount()
})

test('a hand-edit with a fault is told once, and only that override is ignored', async ($, on) => {
  const w = world(on, { files: overridesFile([{ model: 'opus', nudgeAt: 25 }, { window: '1m', nudgeAt: 50 }]) })
  await $.session.start(START)
  await $.session.measure(measure(10))
  await $.session.measure(measure(11))
  const told = w.notices.filter(n => n.includes('overrides.json has a fault'))
  expect(told).toHaveLength(1)
  expect(told[0]).toContain('override 2: window must be a whole number of tokens')
  expect((await voverrides($, '')).text).toContain('model=opus → nudge 25%')
})

test('a file that is not JSON keeps the last good overrides and says so once', async ($, on) => {
  const w = world(on, { files: overridesFile([{ window: 1_000_000, nudgeAt: 25 }]) })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  w.files.set(OVERRIDES, '{ "overrides": [ { "window": 1000000, "nudgeAt": 25 }, ')
  await $.session.measure(measure(26))
  await $.session.measure(measure(27))
  const told = w.notices.filter(n => n.includes("overrides.json can't be read"))
  expect(told).toHaveLength(1)
  expect(told[0]).toContain('window=1M → nudge 25%')
  const ui = await $.ui.mount(BAND())
  expect(await ui.find({ type: 'Text', text: /threshold 25%/ })).toBeDefined()
  await ui.unmount()
})

test('0.1.3 store overrides move into overrides.json once, and leave the store', async ($, on) => {
  const w = world(on, { store: { settings: { nudgeAt: 40, modelThresholds: { '[1m]': { nudgeAt: 50 }, '5-5]': { nudgeAt: 55 } } } } })
  await $.session.start(START)
  expect(JSON.parse(w.files.get(OVERRIDES) ?? '{}')).toEqual({ overrides: [{ window: 200_000, nudgeAt: 70 }, { window: 1_000_000, nudgeAt: 50 }] })
  expect(w.store.get('settings')).toEqual({ nudgeAt: 40 })
  const told = w.notices.filter(n => n.includes('old /vsetup models moved to'))
  expect(told).toHaveLength(1)
  expect(told[0]).toContain('window=1M → nudge 50%')
  expect(told[0]).toContain('not carried over: 5-5] (no equivalent)')
  await endInto($, w, 'clear')
  expect(w.notices.filter(n => n.includes('old /vsetup models moved to'))).toHaveLength(1)
})

test('an override already in the file for the same key stands over a moved one', async ($, on) => {
  const w = world(on, { files: overridesFile([{ window: 1_000_000, nudgeAt: 30 }]), store: { settings: { modelThresholds: { '[1m]': { nudgeAt: 50 } } } } })
  await $.session.start(START)
  expect(JSON.parse(w.files.get(OVERRIDES) ?? '{}')).toEqual({ overrides: [{ window: 1_000_000, nudgeAt: 30 }] })
  expect(w.store.get('settings')).toEqual({})
  const told = w.notices.find(n => n.includes('old /vsetup models moved to'))
  expect(told).toContain('(none)')
  expect(told).toContain('already in the file for the same key, which stays in force: window=1M')
})

test('an ambiguous overrides says so once, and the window wins', async ($, on) => {
  const w = world(on, { files: overridesFile([{ model: 'opus', nudgeAt: 25 }, { window: 1_000_000, nudgeAt: 40 }]) })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.session.measure(measure(31))
  const told = w.notices.filter(n => n.includes('both match this session'))
  expect(told).toEqual(['🔧 model=opus and window=1M both match this session; the window wins (nudgeAt 40%). A model=opus window=1M override would settle it — /vigil-overrides add'])
  const ui = await $.ui.mount(BAND())
  expect(await ui.find({ key: 'handover' })).toBeUndefined()
  await ui.unmount()
})

test('/vigil-overrides lists the overrides and this session, and rm takes one out', async ($, on) => {
  const w = world(on, { files: overridesFile([{ window: 200_000, nudgeAt: 70 }, { model: 'opus5.5', window: 1_000_000, nudgeAt: 20 }]) })
  await $.session.start(START)
  await $.session.measure(measure(10))
  const list = (await voverrides($, '')).text ?? ''
  expect(list).toContain('  model=opus5.5 window=1M → nudge 20%\n  window=200k → nudge 70%\n  otherwise → nudge 35%, step 5%, last light 25%')
  expect(list).toContain('This session (claude-opus-5-5[1m] · 1M): nudge 20% (model=opus5.5 window=1M), step 5% (settings), last light 25% (settings)')
  expect((await voverrides($, 'rm model=opus5.5 window=1m')).text).toContain('nudge 35% (settings)')
  expect(JSON.parse(w.files.get(OVERRIDES) ?? '{}')).toEqual({ overrides: [{ window: 200_000, nudgeAt: 70 }] })
  expect((await voverrides($, 'rm model=haiku')).text).toContain('No override for model=haiku')
  expect((await voverrides($, 'set 20')).text).toContain('/vigil-overrides add')
})

test('/vigil-overrides add asks for an override for this session and writes it', async ($, on) => {
  const w = world(on)
  const answers: Record<string, string> = { '🔧 Covers': 'opus5.5 on 1M', '🎚️ Nudge at': '25%', '📏 Step': 'Inherit (5%)', 'Last light': '50%' }
  w.askReply.value = q => answers[q.header] ?? null
  await $.session.start(START)
  await $.session.measure(measure(10))
  expect((await voverrides($, 'add')).text).toContain('Adding an override')
  await w.clock.settle()
  expect(w.asks.map(q => q.header)).toEqual(['🔧 Covers', '🎚️ Nudge at', '📏 Step', 'Last light'])
  expect(w.asks[0]?.options).toEqual(['opus5.5 on 1M', 'Any model on 1M', 'opus5.5 on any window'])
  expect(JSON.parse(w.files.get(OVERRIDES) ?? '{}')).toEqual({ overrides: [{ window: 200_000, nudgeAt: 70 }, { model: 'opus5.5', window: 1_000_000, nudgeAt: 25, lastLightAt: 50 }] })
  expect(w.notices.some(n => n.includes('model=opus5.5 window=1M → nudge 25%, last light 50%'))).toBe(true)
})

test('answering /vigil-overrides add is presence: the idle window restarts, no unattended handover follows', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  const answers: Record<string, string> = { '🔧 Covers': 'Any model on 200k', '🎚️ Nudge at': '50%', '📏 Step': 'Inherit (5%)', 'Last light': 'Inherit (25%)' }
  w.askReply.value = q => answers[q.header] ?? null
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await w.clock.advance(28 * MIN)
  await voverrides($, 'add')
  await w.clock.settle()
  await w.clock.advance(3 * MIN)                              // 31 min after the prompt, 3 after the answers
  await $.tool.call({ tool: 'Bash', tool_use_id: 'b1' } as never)
  await $.session.measure(measure(41))
  await w.clock.settle()
  expect(w.submits.filter(s => s.text.includes(TOOL)).length).toBe(0)
})

test('an unreadable model: model overrides do not apply, window ones still do', async ($, on) => {
  const w = world(on, { files: overridesFile([{ model: 'opus', nudgeAt: 20 }, { window: 1_000_000, step: 10 }]) })
  w.model.value = null
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(36))
  const ui = await $.ui.mount(BAND())
  expect(await ui.find({ type: 'Text', text: /threshold 35%/ })).toBeDefined()
  expect(await ui.find({ key: 'later', text: /45%/ })).toBeDefined()
  await ui.unmount()
  expect((await voverrides($, '')).text).toContain('model unknown')
})

test('/vigil-overrides add dismissed part-way writes nothing', async ($, on) => {
  const w = world(on)
  w.askReply.value = q => (q.header === '🔧 Covers' ? 'Any model on 1M' : null)
  await $.session.start(START)
  await $.session.measure(measure(10))
  const before = w.files.get(OVERRIDES)
  await voverrides($, 'add')
  await w.clock.settle()
  expect(w.files.get(OVERRIDES)).toBe(before)
  expect(w.notices).toContain('🔧 Override not added — nothing changed')
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

// On the phone the bar and toasts never arrive; a dialog does (Remote Control's "action required").
const PHONE_Q = '🕯️ Context is at 36%. Hand over now?'
const PHONE_OPTS = ['📜 Hand over now', '⏰ Remind me at 40%', '✖ Dismiss'] as const

test('on the phone: a dialog with the bar\'s three choices, and no bar', async ($, on) => {
  const w = world(on)
  w.askAnswer.value = PHONE_OPTS[1]
  await $.session.start(START)
  await $.prompt.submit(human('hi', 'bridge'))
  await $.session.measure(measure(36))
  await w.clock.settle()
  expect(w.asks.map(q => q.question)).toEqual([PHONE_Q])
  expect(w.asks[0]?.options).toEqual(PHONE_OPTS)
  const ui = await $.ui.mount(BAND())
  expect(await ui.find({ key: 'handover' })).toBeUndefined()
  await ui.unmount()
  expect(w.notices).not.toContain('🕯️ Context at 36% — say "hand over" (or /vho) when you\'re ready 📜')
})

test('on the phone: "Hand over now" starts the handover', async ($, on) => {
  const w = world(on)
  w.askAnswer.value = PHONE_OPTS[0]
  await $.session.start(START)
  await $.prompt.submit(human('hi', 'bridge'))
  await $.session.measure(measure(36))
  await w.clock.settle()
  expect(w.submits.at(-1)?.text).toContain(TOOL)
})

test('on the phone: "Remind me" asks again at the next step; a dismissed dialog counts as remind me', async ($, on) => {
  const w = world(on)
  w.askAnswer.value = null                                     // dismissed
  await $.session.start(START)
  await $.prompt.submit(human('hi', 'bridge'))
  await $.session.measure(measure(36))
  await w.clock.settle()
  expect(w.asks).toHaveLength(1)
  w.askAnswer.value = '⏰ Remind me at 45%'
  await $.session.measure(measure(41))
  await w.clock.settle()
  expect(w.asks.map(q => q.question)).toEqual([PHONE_Q, '🕯️ Context is at 41%. Hand over now?'])
  expect(w.state.get('context-vigil-mod.barDismissed')).not.toBe(true)
})

test('on the phone: Dismiss stays silent until a clear', async ($, on) => {
  const w = world(on)
  w.askAnswer.value = PHONE_OPTS[2]
  await $.session.start(START)
  await $.prompt.submit(human('hi', 'bridge'))
  await $.session.measure(measure(36))
  await w.clock.settle()
  await $.session.measure(measure(46))
  await w.clock.settle()
  expect(w.asks).toHaveLength(1)
  expect(w.state.get('context-vigil-mod.barDismissed')).toBe(true)
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
  await $.session.measure(measure(20))
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

test('R1-22: pressing Cancel counts as the person being here', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true, rcAutoClear: 'yes' } } })
  await countdownSession($, w)
  const ui = await $.ui.mount(BAND())
  await ui.press({ key: 'cancel' })
  await ui.unmount()
  await w.clock.settle()
  expect(w.state.get('context-vigil-mod.mode')).toBe('attended')
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

  test('RC no: a hot reload never runs the parked unattended clear; it offers the handover', async ($, on) => {
    const w = world(on, { store: { settings: { auto: true, rcAutoClear: 'no' } } })
    await countdownSession($, w)
    expect(w.commands).not.toContain('clear')
    w.notices.length = 0
    await $.session.start(START)
    await w.clock.advance(60_000)
    expect(w.commands).not.toContain('clear')
    expect(w.notices).toContain(OFFER)
  })

// The phone facts (last human origin, last bridge prompt) must survive a hot reload, or a later
// unattended clear skips the whole RC gate.
async function autoHandoverAfter($: Engine, w: World) {
  await w.clock.advance(31 * MIN)
  await $.tool.call({ tool: 'Bash', tool_use_id: 'b', command: 'ls' } as never)
  await $.session.measure(measure(20))
  await $.session.measure(measure(36))
  await w.clock.settle()
  await $.tool.call({ tool: TOOL, tool_use_id: 'h', goal: 'G', state: 'S', next_step: 'N', session_name: 'Name' } as never)
  await w.clock.advance(60_000)
}

  test('RC no: a new unattended handover after a reload still meets the RC gate', async ($, on) => {
    const w = world(on, { store: { settings: { auto: true, rcAutoClear: 'no' } } })
    await $.session.start(START)
    await $.prompt.submit(human('go', 'bridge'))
    await $.session.start(START)          // the reload
    await autoHandoverAfter($, w)
    expect(w.submits.some(s => s.text.includes(TOOL))).toBe(true)
    expect(w.commands).not.toContain('clear')
  })

  test('RC no: a deferred handover drained by the latch still meets the RC gate', async ($, on) => {
    const w = world(on, { now: 1_000_000, store: { settings: { auto: true, rcAutoClear: 'no' }, latch: { kind: 'five_hour', resetsAtMs: 1_000_000 + 60 * MIN } } })
    await $.session.start(START)
    await $.prompt.submit(human('go', 'bridge'))
    await w.clock.advance(31 * MIN)
    await $.tool.call({ tool: 'Bash', tool_use_id: 'b', command: 'ls' } as never)
    await $.session.measure(measure(20))
    await $.session.measure(measure(36))          // armed while latched: deferred
    await w.clock.settle()
    expect(w.state.get('context-vigil-mod.deferred')).toMatchObject({ reason: 'threshold' })
    await w.clock.advance(30 * MIN)               // past the reset
    await $.session.measure(measure(36))          // the lifted latch drains it, as an unattended handover
    await w.clock.settle()
    expect(w.submits.some(s => s.text.includes(TOOL))).toBe(true)
    await $.tool.call({ tool: TOOL, tool_use_id: 'h', goal: 'G', state: 'S', next_step: 'N', session_name: 'Name' } as never)
    await w.clock.advance(60_000)
    expect(w.commands).not.toContain('clear')
  })

test('RC unanswered: after a reload the phone is still on the countdown path, never a bare clear', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await $.session.start(START)
  await $.prompt.submit(human('go', 'bridge'))
  await $.session.start(START)          // the reload
  await autoHandoverAfter($, w)
  expect(w.submits.some(s => s.text.includes(TOOL))).toBe(true)
  expect(w.notices).toContain('🧹 Handing over in 30 s — send anything to cancel')
  await w.clock.advance(30_000)
  expect(w.commands).toContain('clear')
})

test('the phone facts cross a clear and a reload after it', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true, rcAutoClear: 'no' } } })
  await $.session.start(START)
  await $.prompt.submit(human('go', 'bridge'))
  w.sessionId.value = 's2'
  await endInto($, w, 'clear')
  expect(w.state.get('context-vigil-mod.phoneFacts')).toMatchObject({ lastHumanOrigin: 'bridge' })
  await $.session.start(START)            // a reload in the new session
  await autoHandoverAfter($, w)
  expect(w.submits.some(s => s.text.includes(TOOL))).toBe(true)
  expect(w.commands).not.toContain('clear')
})

test('pressing a bar button is presence: the idle window restarts, no unattended handover follows (R2-07)', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await w.clock.advance(28 * MIN)
  await $.tool.call({ tool: 'Bash', tool_use_id: 'b0' } as never)
  await $.session.measure(measure(36))                       // attended at 28 min: the bar
  let ui = await $.ui.mount(BAND())
  await ui.press({ key: 'later' })
  await ui.unmount()
  await w.clock.advance(3 * MIN)                              // 31 min after the prompt, 3 after the press
  await $.tool.call({ tool: 'Bash', tool_use_id: 'b1' } as never)
  await $.session.measure(measure(41))
  await w.clock.settle()
  expect(w.submits.filter(s => s.text.includes(TOOL)).length).toBe(0)
  ui = await $.ui.mount(BAND())
  expect(await ui.find({ key: 'handover' })).toBeDefined()    // still a nudge for the person who is here
  await ui.unmount()
})

test('RC countdown: a held notification does not cancel it', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true, rcAutoClear: 'yes' } } })
  await countdownSession($, w)
  await $.prompt.submit({ text: 'agent finished', wait: false, origin: { kind: 'task-notification' } as never })
  await w.clock.advance(31_000)
  expect(w.commands).toContain('clear')
})

const NOTE = { text: 'agent finished', wait: false, origin: { kind: 'task-notification' } as never }

test('a held notification goes back to the live session when the countdown is cancelled, and is not in the later resume', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true, rcAutoClear: 'yes' } } })
  await countdownSession($, w)
  await $.prompt.submit(NOTE)
  expect(w.state.get('context-vigil-mod.pending')).toMatchObject({ held: ['agent finished'] })
  w.submits.length = 0
  await $.prompt.submit(human('wait!', 'bridge'))   // cancels the countdown
  await w.clock.advance(1000)
  expect(w.submits.some(s => s.text === 'agent finished' && s.origin !== 'task-notification')).toBe(true)
  expect(w.state.get('context-vigil-mod.pending')).not.toHaveProperty('held')
  w.submits.length = 0
  w.sessionId.value = 's2'
  await endInto($, w, 'clear')
  await w.clock.advance(500)
  expect(w.submits.some(s => s.text.includes('agent finished'))).toBe(false)
  expect(w.notices.some(n => n.includes('agent finished'))).toBe(false)
})

test('a held notification goes back to the live session when the clear is rejected', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true, rcAutoClear: 'yes' } } })
  await countdownSession($, w)
  await $.prompt.submit(NOTE)
  w.clearRefused.value = true
  w.submits.length = 0
  await w.clock.advance(35_000)
  expect(w.submits.some(s => s.text === 'agent finished')).toBe(true)
})

// A requested handover whose clear waits on a draft.
const vhoCmd = { command: 'vho', args: '', origin: { kind: 'composer' } as never } as never
const callH = { tool: TOOL, tool_use_id: 'h1', goal: 'G', state: 'S', next_step: 'N', session_name: 'Name' } as never
async function draftWaiting($: Engine, w: World, reply: string | null | 'open') {
  if (reply !== 'open') w.askReply.value = () => reply
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.command.run(vhoCmd)
  await w.clock.settle()
  w.draft.value = 'half a sen'
  await $.tool.call(callH)
  await w.clock.settle()
}
const draftAsks = (w: World) => w.asks.filter(q => q.question === '⏸️ Auto-clear paused while you\'re typing')

test('a clear waiting on a draft asks once, however long it waits', async ($, on) => {
  const w = world(on)
  await draftWaiting($, w, 'open')
  expect(draftAsks(w).length).toBe(1)
  expect(draftAsks(w)[0]?.options).toEqual(['🧹 Clear and resume now', '⏰ Postpone 5%'])
  await w.clock.advance(20_000)
  expect(draftAsks(w).length).toBe(1)
  expect(w.commands).not.toContain('clear')
})

test('the band says the handover is paused while the clear waits on a draft, and stops when it clears', async ($, on) => {
  const w = world(on)
  await draftWaiting($, w, 'open')
  let ui = await $.ui.mount(BAND())
  expect(await ui.find({ type: 'Text', text: /Auto-clear paused while you're typing/ })).toBeDefined()
  await ui.unmount()
  w.draft.value = ''
  await w.clock.advance(3000)
  ui = await $.ui.mount(BAND())
  expect(await ui.find({ type: 'Text', text: /Auto-clear paused/ })).toBeUndefined()
  await ui.unmount()
})

test('Clear and resume now: the clear goes despite the draft, which is sent as the person\'s after the resume', async ($, on) => {
  const w = world(on)
  await draftWaiting($, w, '🧹 Clear and resume now')
  await w.clock.advance(100)
  expect(w.commands).toContain('clear')
  expect(w.draft.value).toBe('')
  w.sessionId.value = 's2'
  await endInto($, w, 'clear')
  await w.clock.advance(500)
  expect(w.submits.at(-1)?.text).toContain('half a sen')
})

test('Postpone: no clear, the pending is dropped, and the next step hands over afresh', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.session.measure(measure(36))
  await draftWaiting($, w, '⏰ Postpone 5%')
  await w.clock.advance(100)
  expect(w.commands).not.toContain('clear')
  expect(w.state.get('context-vigil-mod.pending')).toBeNull()
  expect(w.state.get('context-vigil-mod.lastNudged')).toBe(35)
  await $.session.measure(measure(41))
  expect(w.state.get('context-vigil-mod.lastNudged')).toBe(40)
})

test('a dismissed dialog postpones', async ($, on) => {
  const w = world(on)
  await draftWaiting($, w, null)
  await w.clock.advance(100)
  expect(w.commands).not.toContain('clear')
  expect(w.state.get('context-vigil-mod.pending')).toBeNull()
})

test('Clear and resume now on an auto (unattended) handover clears: the choice makes it an attended clear', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  w.askReply.value = () => '🧹 Clear and resume now'
  await $.session.start(START)
  await $.prompt.submit(human('go'))
  await w.clock.advance(31 * MIN)
  await $.tool.call({ tool: 'Bash', tool_use_id: 'b', command: 'ls' } as never)
  await $.session.measure(measure(20))
  await $.session.measure(measure(36))
  await w.clock.settle()
  await $.tool.call({ tool: TOOL, tool_use_id: 'h', goal: 'G', state: 'S', next_step: 'N', session_name: 'Name' } as never)
  w.draft.value = 'half a sen'                         // typed after the tool hook's own look at the box
  await w.clock.settle()
  await w.clock.advance(100)
  expect(w.commands).toContain('clear')
  w.sessionId.value = 's2'
  await endInto($, w, 'clear')
  await w.clock.advance(500)
  expect(w.submits.at(-1)?.text).toContain('half a sen')
})

test('the choice does not outlive its clear: rejected, a later handover still waits on a draft and asks again', async ($, on) => {
  const w = world(on)
  w.clearRefused.value = true
  await draftWaiting($, w, '🧹 Clear and resume now')   // Clear now: the clear is tried, the engine refuses it
  await w.clock.advance(100)
  expect(w.notices.some(n => n.includes('rejected') || n.includes('refused') || n.includes("couldn't"))).toBe(true)
  w.clearRefused.value = false
  w.draft.value = 'new draft'
  await w.clock.advance(2 * MIN)
  await $.turn.complete(turn('x'))                     // the old handover is stale: a new one is written
  w.askReply.value = null
  w.commands.length = 0
  await $.command.run(vhoCmd)
  await w.clock.settle()
  await $.tool.call({ ...(callH as object), tool_use_id: 'h2' } as never)
  await w.clock.settle()
  await w.clock.advance(5000)
  expect(w.commands).not.toContain('clear')
  expect(draftAsks(w).length).toBe(2)
})

test('the threshold bar takes precedence over the paused line', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.session.measure(measure(41))                 // the bar is up
  await draftWaiting($, w, 'open')
  const ui = await $.ui.mount(BAND())
  expect(await ui.find({ key: 'handover' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /Auto-clear paused/ })).toBeUndefined()
  await ui.unmount()
})
