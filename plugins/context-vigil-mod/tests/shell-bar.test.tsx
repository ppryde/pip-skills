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
  await $.classic.SessionStart({ source: 'clear' } as never)
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

for (const rcAutoClear of ['no'] as const) {
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
  await $.session.measure(measure(20))
  await $.session.measure(measure(36))
  await w.clock.settle()
  await $.tool.call({ tool: TOOL, tool_use_id: 'h', goal: 'G', state: 'S', next_step: 'N', session_name: 'Name' } as never)
  await w.clock.advance(60_000)
}

for (const rcAutoClear of ['no'] as const) {
  test(`RC ${rcAutoClear}: a new unattended handover after a reload still meets the RC gate`, async ($, on) => {
    const w = world(on, { store: { settings: { auto: true, rcAutoClear } } })
    await $.session.start(START)
    await $.prompt.submit(human('go', 'bridge'))
    await $.session.start(START)          // the reload
    await autoHandoverAfter($, w)
    expect(w.submits.some(s => s.text.includes(TOOL))).toBe(true)
    expect(w.commands).not.toContain('clear')
  })

  test(`RC ${rcAutoClear}: a deferred handover drained by the latch still meets the RC gate`, async ($, on) => {
    const w = world(on, { now: 1_000_000, store: { settings: { auto: true, rcAutoClear }, latch: { kind: 'five_hour', resetsAtMs: 1_000_000 + 60 * MIN } } })
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
