import { expect, test } from 'claude-code/testing'
import { STEPS, TELL } from '../plugin/core/setup'
import { START, human, world, type AskSeen } from './world'

const MIN = 60_000
const TOOL = 'mcp__context-vigil-mod__vigil_handover'
const ask = (questions: { question: string }[], answers: Record<string, string>) =>
  ({ tool: 'AskUserQuestion', tool_use_id: 'q', questions, answers })
const setup = (args = '') => ({ command: 'vigil-setup', args, origin: { kind: 'composer' } as never } as never)
const SAVED = '⚙️ context-vigil-mod settings saved'
const STOPPED = '⚙️ Setup stopped — what you answered is saved; /vigil-setup to finish'
// Answers each dialog by its header; a header not listed is dismissed.
const byHeader = (answers: Record<string, string>) => (q: AskSeen) => answers[q.header] ?? null
const pluginSubmits = (w: ReturnType<typeof world>) => w.submits.filter(x => x.origin === 'plugin')

test('/vigil-setup asks each step itself, one dialog at a time, with no prompt to the model', async ($, on) => {
  const w = world(on)
  w.askReply.value = byHeader({
    [STEPS.nudge.header]: '50%', [STEPS.bar.header]: 'Off', [STEPS.auto.header]: 'On', [STEPS.idle.header]: '15 min', [STEPS.rc.header]: 'No',
    [STEPS.last_light.header]: 'Off (Recommended)', [STEPS.limits.header]: 'On (Recommended)',
    [STEPS.limit_pct.header]: '97', [STEPS.limit_windows.header]: 'Weekly (seven_day)',
  })
  await $.session.start(START)
  await $.command.run(setup())
  await w.clock.settle()
  expect(w.asks.map(q => q.header)).toEqual(['🎚️ Nudge at', '🎛️ The bar', '🤖 Auto mode', '⏱️ Idle time', '📱 RC clear', 'Last light', '⏳ Limits', '⏳ Trigger %', '⏳ Windows'])
  expect(pluginSubmits(w)).toEqual([])
  // Labels only: nothing for AskUserQuestion to draw on a second line.
  expect(w.asks.flatMap(q => q.descriptions).every(d => d === '')).toBe(true)
  expect(w.asks[0]?.options).toEqual(['25%', '35% (Recommended)', '50%', TELL])
  expect(w.asks.at(-1)?.multiSelect).toBe(true)
  expect(w.store.get('settings')).toMatchObject({ nudgeAt: 50, bar: false, auto: true, idleMin: 15, rcAutoClear: 'no', lastLight: false, limits: true, limitPct: 97, limitWindows: ['seven_day'] })
  expect(w.notices).toContain(SAVED)
})

test('Tell me more re-asks that step with the explanation, then takes the answer', async ($, on) => {
  const w = world(on)
  let n = 0
  w.askReply.value = () => (n++ === 0 ? TELL : 'Off')
  await $.session.start(START)
  await $.command.run(setup('bar'))
  await w.clock.settle()
  expect(w.asks).toHaveLength(2)
  expect(w.asks[1]?.question).toContain('1 hand over · 2 remind me at +5% · 0 dismiss')
  expect(w.asks[1]?.question.endsWith(STEPS.bar.question)).toBe(true)
  expect(w.store.get('settings')).toMatchObject({ bar: false })
  expect(pluginSubmits(w)).toEqual([])
})

test('a dismissed dialog stops setup; what was answered before it is kept', async ($, on) => {
  const w = world(on)
  w.askReply.value = byHeader({ [STEPS.nudge.header]: '50%' })   // the bar's dialog is dismissed
  await $.session.start(START)
  await $.command.run(setup())
  await w.clock.settle()
  expect(w.asks.map(q => q.header)).toEqual(['🎚️ Nudge at', '🎛️ The bar'])
  expect(w.store.get('settings')).toMatchObject({ nudgeAt: 50 })
  expect(w.notices).not.toContain(SAVED)
  expect(w.notices).toContain(STOPPED)
})

test('a /vigil-setup that takes over while the last answer is being logged wins: the old run saves nothing', async ($, on) => {
  const w = world(on)
  w.askReply.value = byHeader({ [STEPS.nudge.header]: '50%', [STEPS.bar.header]: 'Off' })
  await $.session.start(START)
  let release = () => {}
  w.fsRead.gate = new Promise<void>(res => { release = res })   // holds the event-log append
  await $.command.run(setup('nudge'))
  await w.clock.settle()
  await $.command.run(setup('bar'))   // takes over while the nudge answer's log line waits
  w.fsRead.gate = null
  release()
  await w.clock.settle()
  expect(w.store.get('settings')).toMatchObject({ nudgeAt: 35, bar: false })
})

test('/vigil-setup <step> asks only that step and the ones it decides', async ($, on) => {
  const w = world(on)
  w.askReply.value = byHeader({ [STEPS.limits.header]: 'On (Recommended)', [STEPS.limit_pct.header]: '90%', [STEPS.limit_windows.header]: 'Spend cap (spend_limit)' })
  await $.session.start(START)
  await $.command.run(setup('limits'))
  await w.clock.settle()
  expect(w.asks.map(q => q.header)).toEqual(['⏳ Limits', '⏳ Trigger %', '⏳ Windows'])
  expect(w.store.get('settings')).toMatchObject({ limitPct: 90, limitWindows: ['spend_limit'] })
  expect(w.notices).toContain(SAVED)
})

test('an Other answer that does not fit is asked again with the explanation', async ($, on) => {
  const w = world(on)
  const pct: string[] = ['95abc', '96']
  const windows: string[] = ['monthly', 'Weekly (seven_day), Spend cap (spend_limit)']
  w.askReply.value = q => q.header === STEPS.limits.header ? 'On (Recommended)'
    : q.header === STEPS.limit_pct.header ? (pct.shift() ?? null)
      : q.header === STEPS.limit_windows.header ? (windows.shift() ?? null) : null
  await $.session.start(START)
  await $.command.run(setup('limits'))
  await w.clock.settle()
  expect(w.asks.map(q => q.header)).toEqual(['⏳ Limits', '⏳ Trigger %', '⏳ Trigger %', '⏳ Windows', '⏳ Windows'])
  expect(w.asks[2]?.question.startsWith(STEPS.limit_pct.explain)).toBe(true)
  expect(w.store.get('settings')).toMatchObject({ limitPct: 96, limitWindows: ['seven_day', 'spend_limit'] })
})

test('answers to questions that are not ours are left alone', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  const r = await $.tool.call(ask([{ question: 'Unrelated?' }], { 'Unrelated?': 'A' }) as never)
  expect((r as { context?: string[] }).context).toBeUndefined()
  expect(w.notices).not.toContain(SAVED)
  expect(w.store.get('settings')).toBeUndefined()
})

test('/vigil-setup with an unknown step shows the usage, asks nothing, saves nothing', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run(setup('bogus'))
  await w.clock.settle()
  expect(w.notices).toContain('⚙️ /vigil-setup [nudge|bar|auto|last-light|limits|rc] — that step name is not one of these')
  expect(w.notices).not.toContain(SAVED)
  expect(w.asks).toEqual([])
  expect(pluginSubmits(w)).toEqual([])
})

// Auto mode arming in a session whose last human prompt came from the phone.
async function armOnPhone($: never, w: ReturnType<typeof world>) {
  const e = $ as unknown as { session: { start: (x: unknown) => Promise<unknown> }; prompt: { submit: (x: unknown) => Promise<unknown> }; tool: { call: (x: unknown) => Promise<unknown> } }
  await e.session.start(START)
  await e.prompt.submit(human('go', 'bridge'))
  await w.clock.advance(31 * MIN)
  await e.tool.call({ tool: 'Bash', tool_use_id: 'b', command: 'ls' })   // auto mode would arm now
  await w.clock.settle()
}

const rcAsks = (w: ReturnType<typeof world>) => w.asks.filter(q => q.header === STEPS.rc.header)
const HINT = '📱 Auto-clear also runs on the phone — /vigil-setup rc to change'

test('unset RC answer on the phone with auto on: never asks, one hint, and the clear runs the safeguarded countdown', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await armOnPhone($ as never, w)
  expect(rcAsks(w)).toEqual([])
  expect(w.asks).toEqual([])
  expect(pluginSubmits(w)).toEqual([])
  expect(w.notices.filter(n => n === HINT)).toHaveLength(1)
  await w.clock.advance(31 * MIN)
  await $.tool.call({ tool: 'Bash', tool_use_id: 'b2', command: 'ls' } as never)
  await w.clock.settle()
  expect(w.notices.filter(n => n === HINT)).toHaveLength(1)   // once per session
  await $.session.measure({ context: { window: 1_000_000, percent: 20 }, rateLimits: [], changed: ['context'] as never })
  await $.session.measure({ context: { window: 1_000_000, percent: 36 }, rateLimits: [], changed: ['context'] as never })
  await w.clock.settle()
  await $.tool.call({ tool: TOOL, tool_use_id: 'h', goal: 'G', state: 'S', next_step: 'N', session_name: 'Name' } as never)
  await w.clock.settle()
  expect(w.notices).toContain('🧹 Handing over in 30 s — send anything to cancel')
  expect(w.commands).not.toContain('clear')
  await w.clock.advance(30_000)
  expect(w.commands).toContain('clear')
  expect(rcAsks(w)).toEqual([])
})

test('RC answered Yes in setup: no hint, and the unattended clear on the phone goes through the countdown', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true, rcAutoClear: 'yes' } } })
  await armOnPhone($ as never, w)
  expect(w.notices).not.toContain(HINT)
  await w.clock.advance(31 * MIN)
  await $.tool.call({ tool: 'Bash', tool_use_id: 'b3', command: 'ls' } as never)
  await $.session.measure({ context: { window: 1_000_000, percent: 20 }, rateLimits: [], changed: ['context'] as never })
  await $.session.measure({ context: { window: 1_000_000, percent: 36 }, rateLimits: [], changed: ['context'] as never })
  await w.clock.settle()
  await $.tool.call({ tool: TOOL, tool_use_id: 'h', goal: 'G', state: 'S', next_step: 'N', session_name: 'Name' } as never)
  await w.clock.settle()
  expect(w.notices).toContain('🧹 Handing over in 30 s — send anything to cancel')
  await w.clock.advance(30_000)
  expect(w.commands).toContain('clear')
})

test('/vigil-setup rc still asks the phone question explicitly, and saves it', async ($, on) => {
  const w = world(on)
  w.askReply.value = byHeader({ [STEPS.rc.header]: 'Yes (Recommended)' })
  await $.session.start(START)
  await $.command.run(setup('rc'))
  await w.clock.settle()
  expect(rcAsks(w)).toHaveLength(1)
  expect(w.store.get('settings')).toMatchObject({ rcAutoClear: 'yes' })
})

const at = (percent: number) => ({ context: { window: 1_000_000, percent }, rateLimits: [], changed: ['context'] as never })
const handWritten = { tool: TOOL, tool_use_id: 'h', goal: 'G', state: 'S', next_step: 'N', session_name: 'Name' } as never

test('R1-03: any answered AskUserQuestion counts as presence, the mod asked it or not', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await $.session.start(START)
  await w.clock.advance(31 * MIN)
  await $.tool.call({ tool: 'Bash', tool_use_id: 'b', command: 'ls' } as never)
  expect(w.state.get('context-vigil-mod.mode')).toBe('auto')
  await $.tool.call({ tool: 'AskUserQuestion', tool_use_id: 'q2', questions: [{ question: 'Pick?' }], answers: { 'Pick?': 'A' } } as never)
  expect(w.state.get('context-vigil-mod.mode')).toBe('attended')
})

test('RC answered No in setup: no hint, and the unattended clear on the phone never runs', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true, rcAutoClear: 'no' } } })
  await armOnPhone($ as never, w)
  expect(w.notices).not.toContain(HINT)
  await w.clock.advance(31 * MIN)                // answering was presence: wait out the idle window
  await $.tool.call({ tool: 'Bash', tool_use_id: 'b3', command: 'ls' } as never)
  await $.session.measure({ context: { window: 1_000_000, percent: 20 }, rateLimits: [], changed: ['context'] as never })
  await $.session.measure({ context: { window: 1_000_000, percent: 36 }, rateLimits: [], changed: ['context'] as never })
  await w.clock.settle()
  await $.tool.call({ tool: TOOL, tool_use_id: 'h', goal: 'G', state: 'S', next_step: 'N', session_name: 'Name' } as never)
  await w.clock.advance(60_000)
  expect(w.notices).toContain('📱 Handover saved — auto-clear is off for Remote Control sessions')
  expect(w.commands).not.toContain('clear')
})

test('/vigil-setup toString is an unknown step, not a crash', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run(setup('toString'))
  await w.clock.settle()
  expect(w.notices).toContain('⚙️ /vigil-setup [nudge|bar|auto|last-light|limits|rc] — that step name is not one of these')
})

test('a clear landing while an answer is saved stops setup: nothing is asked into the new session', async ($, on) => {
  const w = world(on)
  w.askReply.value = byHeader({ [STEPS.nudge.header]: '50%', [STEPS.bar.header]: 'Off' })
  w.onStoreSet.value = async key => {
    if (key !== 'settings') return
    w.onStoreSet.value = null
    w.sessionId.value = 's2'
    await $.classic.SessionStart({ source: 'clear' } as never)
  }
  await $.session.start(START)
  await $.command.run(setup())
  await w.clock.settle()
  expect(w.store.get('settings')).toMatchObject({ nudgeAt: 50 })
  expect(w.asks.map(q => q.header)).toEqual(['🎚️ Nudge at'])
  expect(w.notices).not.toContain(SAVED)
})

test('a dialog still open across a clear is inert when it is answered', async ($, on) => {
  const w = world(on)
  w.askHold.held = true
  await $.session.start(START)
  await $.command.run(setup())
  await w.clock.settle()
  expect(w.asks).toHaveLength(1)
  w.sessionId.value = 's2'
  await $.classic.SessionStart({ source: 'clear' } as never)
  w.askHold.waiting[0]?.('50%')
  await w.clock.settle()
  expect(w.store.get('settings')).toBeUndefined()
  expect(w.asks).toHaveLength(1)
})

// R1-06: settings are an account fact; another session's change is seen at the next decision.
test('R1-06: auto switched off by another session stops this one at the threshold', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await $.session.start(START)
  await $.prompt.submit(human('go'))
  await w.clock.advance(31 * MIN)
  await $.tool.call({ tool: 'Bash', tool_use_id: 'b', command: 'ls' } as never)
  await $.session.measure(at(20))
  w.store.set('settings', { auto: false })           // session A answered Off
  await $.session.measure(at(36))
  await w.clock.settle()
  expect(w.submits.some(s => s.text.includes(TOOL))).toBe(false)
})

test('R1-06: answering a step keeps what another session changed', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  w.askHold.held = true
  await $.session.start(START)
  await $.command.run(setup('nudge'))
  await w.clock.settle()
  w.store.set('settings', { auto: false, rcAutoClear: 'yes' })   // session A, meanwhile
  w.askHold.waiting[0]?.('50%')
  await w.clock.settle()
  expect(w.store.get('settings')).toMatchObject({ nudgeAt: 50, auto: false, rcAutoClear: 'yes' })
})

test('R1-21: with classic active, the RC hint is never shown and nothing is asked', async ($, on) => {
  const classic = JSON.stringify({ hooks: { Stop: [{ hooks: [{ type: 'command', command: '"/s/context-vigil/scripts/context-vigil" hook stop' }] }] } })
  const w = world(on, { store: { settings: { auto: true } }, files: { '/cfg/settings.json': classic } })
  await armOnPhone($ as never, w)
  expect(pluginSubmits(w)).toEqual([])   // 'go' is the test's own prompt
  expect(w.asks).toEqual([])
  expect(w.notices).not.toContain(HINT)
})

test('R1-21: while the usage limit is latched, the RC hint is not shown', async ($, on) => {
  const w = world(on, { now: 1_000_000, store: { settings: { auto: true }, latch: { kind: 'five_hour', resetsAtMs: 1_000_000 + 10 * 3_600_000 } } })
  await armOnPhone($ as never, w)
  expect(w.asks).toEqual([])
  expect(w.notices).not.toContain(HINT)
})
