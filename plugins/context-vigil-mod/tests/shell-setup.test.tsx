import { expect, test } from 'claude-code/testing'
import { START, human, world } from './world'

const MIN = 60_000
const TOOL = 'mcp__context-vigil-mod__vigil_handover'
const ask = (questions: { question: string }[], answers: Record<string, string>) =>
  ({ tool: 'AskUserQuestion', tool_use_id: 'q', questions, answers })
const cardOf = (text: string) => JSON.parse(text.slice(text.indexOf('[{'), text.lastIndexOf('}]') + 2)) as { header: string; question: string }[]
const setup = (args = '') => ({ command: 'vsetup', args, origin: { kind: 'composer' } as never } as never)

test('/vsetup asks card 1 through the model, saves the answers, follows with card 2', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run(setup())
  await w.clock.settle()
  const prompt = w.submits.at(-1)?.text ?? ''
  expect(prompt).toContain('AskUserQuestion')
  const card = cardOf(prompt)
  expect(card.map(q => q.header)).toEqual(['🎚️ Nudge at', '🎛️ The bar', '🤖 Auto mode', 'Last light'])
  const answers = Object.fromEntries(card.map(q => [q.question, q.header.includes('Auto') ? 'On' : q.header.includes('Nudge') ? '50%' : 'Off']))
  const r = await $.tool.call(ask(card, answers) as never)
  const next = JSON.stringify((r as { context?: string[] }).context ?? [])
  expect(next).toContain('⏱️ Idle time')
  expect(next).toContain('⏳ Limits')
  expect(next).not.toContain('⏳ Trigger %')
  expect(w.store.get('settings')).toMatchObject({ nudgeAt: 50, bar: false, auto: true, lastLight: false })
})

test('Tell me more re-asks that question with the explanation', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run(setup('bar'))
  await w.clock.settle()
  const card = cardOf(w.submits.at(-1)?.text ?? '')
  const r = await $.tool.call(ask(card, { [card[0]?.question ?? '']: 'Tell me more' }) as never)
  expect(JSON.stringify((r as { context?: string[] }).context ?? [])).toContain('1 hand over · 2 remind me at +5% · 0 dismiss')
})

test('answers to questions that are not ours are left alone', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run(setup('bar'))
  await w.clock.settle()
  const r = await $.tool.call(ask([{ question: 'Unrelated?' }], { 'Unrelated?': 'A' }) as never)
  expect((r as { context?: string[] }).context).toBeUndefined()
  expect(w.notices).not.toContain('⚙️ context-vigil-mod settings saved')
  expect(w.store.get('settings')).toBeUndefined()
})

test('/vsetup with an unknown step shows the usage, asks nothing, saves nothing', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run(setup('bogus'))
  await w.clock.settle()
  expect(w.notices).toContain('⚙️ /vsetup [nudge|bar|auto|last-light|limits|rc] — that step name is not one of these')
  expect(w.notices).not.toContain('⚙️ context-vigil-mod settings saved')
  expect(w.submits.some(s => s.text.includes('AskUserQuestion'))).toBe(false)
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

test('the RC question is asked once, when auto mode would first arm on the phone', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await armOnPhone($ as never, w)
  expect(w.notices).toContain('📱 First Remote Control session with auto mode — one quick question about auto-clear')
  expect(w.submits.filter(s => s.text.includes('📱 RC clear')).length).toBe(1)
  await $.prompt.submit(human('back', 'bridge'))
  await w.clock.advance(31 * MIN)
  await $.tool.call({ tool: 'Bash', tool_use_id: 'b2', command: 'ls' } as never)
  await w.clock.settle()
  expect(w.submits.filter(s => s.text.includes('📱 RC clear')).length).toBe(1)
})

test('the RC question is not asked again after a /clear', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await armOnPhone($ as never, w)
  expect(w.submits.filter(s => s.text.includes('📱 RC clear')).length).toBe(1)
  w.sessionId.value = 's2'
  await $.classic.SessionStart({ source: 'clear' } as never)
  await $.prompt.submit(human('back', 'bridge'))
  await w.clock.advance(31 * MIN)
  await $.tool.call({ tool: 'Bash', tool_use_id: 'b2', command: 'ls' } as never)
  await w.clock.settle()
  expect(w.submits.filter(s => s.text.includes('📱 RC clear')).length).toBe(1)
})

test('RC answered Yes: saved, and the unattended clear on the phone goes through the countdown', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await armOnPhone($ as never, w)
  const card = cardOf(w.submits.at(-1)?.text ?? '')
  await $.tool.call(ask(card, { [card[0]?.question ?? '']: 'Yes' }) as never)
  expect(w.store.get('settings')).toMatchObject({ rcAutoClear: 'yes' })
  await w.clock.advance(31 * MIN)                // answering was presence: wait out the idle window
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

const at = (percent: number) => ({ context: { window: 1_000_000, percent }, rateLimits: [], changed: ['context'] as never })
const handWritten = { tool: TOOL, tool_use_id: 'h', goal: 'G', state: 'S', next_step: 'N', session_name: 'Name' } as never

// R1-03: an answered card is the person being here.
test('R1-03: answering Yes to a parked unattended clear offers it, never runs it', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await armOnPhone($ as never, w)
  const card = cardOf(w.submits.at(-1)?.text ?? '')
  await $.session.measure(at(20))
  await $.session.measure(at(36))
  await w.clock.settle()
  await $.tool.call(handWritten)
  await w.clock.settle()
  expect(w.notices).toContain('📱 Handover saved — auto-clear in Remote Control is not switched on (/vsetup rc)')
  w.notices.length = 0
  await $.tool.call(ask(card, { [card[0]?.question ?? '']: 'Yes' }) as never)
  await w.clock.advance(31_000)
  expect(w.commands).not.toContain('clear')
  expect(w.state.get('context-vigil-mod.mode')).toBe('attended')
  expect(w.notices.some(n => n.includes('A handover is waiting'))).toBe(true)
})

test('R1-03: any answered AskUserQuestion counts as presence, the mod asked it or not', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await $.session.start(START)
  await w.clock.advance(31 * MIN)
  await $.tool.call({ tool: 'Bash', tool_use_id: 'b', command: 'ls' } as never)
  expect(w.state.get('context-vigil-mod.mode')).toBe('auto')
  await $.tool.call({ tool: 'AskUserQuestion', tool_use_id: 'q2', questions: [{ question: 'Pick?' }], answers: { 'Pick?': 'A' } } as never)
  expect(w.state.get('context-vigil-mod.mode')).toBe('attended')
})

test('RC answered No: saved, and the unattended clear on the phone never runs', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await armOnPhone($ as never, w)
  const card = cardOf(w.submits.at(-1)?.text ?? '')
  await $.tool.call(ask(card, { [card[0]?.question ?? '']: 'No' }) as never)
  expect(w.store.get('settings')).toMatchObject({ rcAutoClear: 'no' })
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

test('/vsetup toString is an unknown step, not a crash', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run(setup('toString'))
  await w.clock.settle()
  expect(w.notices).toContain('⚙️ /vsetup [nudge|bar|auto|last-light|limits|rc] — that step name is not one of these')
})

test('a clear landing while setup answers are saved does not break the answer hook', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run(setup())
  await w.clock.settle()
  const card = cardOf(w.submits.at(-1)?.text ?? '')
  w.onStoreSet.value = async key => {
    if (key !== 'settings') return
    w.onStoreSet.value = null
    w.sessionId.value = 's2'
    await $.classic.SessionStart({ source: 'clear' } as never)
  }
  const answers = Object.fromEntries(card.map(q => [q.question, q.header.includes('Nudge') ? '50%' : 'Off']))
  const r = await $.tool.call(ask(card, answers) as never)
  expect((r as { deny?: string }).deny).toBeUndefined()
  expect(w.store.get('settings')).toMatchObject({ nudgeAt: 50 })
  expect(JSON.stringify((r as { context?: string[] }).context ?? [])).toContain('⏳ Limits')
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

test('R1-06: answering a card keeps what another session changed', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await $.session.start(START)
  await $.command.run(setup('nudge'))
  await w.clock.settle()
  const card = cardOf(w.submits.at(-1)?.text ?? '')
  w.store.set('settings', { auto: false, rcAutoClear: 'yes' })   // session A, meanwhile
  await $.tool.call(ask(card, { [card[0]?.question ?? '']: '50%' }) as never)
  expect(w.store.get('settings')).toMatchObject({ nudgeAt: 50, auto: false, rcAutoClear: 'yes' })
})

test('R1-21: with classic active, the RC question is never submitted', async ($, on) => {
  const classic = JSON.stringify({ hooks: { Stop: [{ hooks: [{ type: 'command', command: '"/s/context-vigil/scripts/context-vigil" hook stop' }] }] } })
  const w = world(on, { store: { settings: { auto: true } }, files: { '/cfg/settings.json': classic } })
  await armOnPhone($ as never, w)
  expect(w.submits.filter(x => x.origin === 'plugin')).toEqual([])   // 'go' is the test's own prompt
  expect(w.notices).not.toContain('📱 First Remote Control session with auto mode — one quick question about auto-clear')
})

test('R1-21: while the usage limit is latched, the RC question is not submitted', async ($, on) => {
  const w = world(on, { now: 1_000_000, store: { settings: { auto: true }, latch: { kind: 'five_hour', resetsAtMs: 1_000_000 + 10 * 3_600_000 } } })
  await armOnPhone($ as never, w)
  expect(w.submits.filter(s => s.text.includes('📱 RC clear'))).toHaveLength(0)
})
