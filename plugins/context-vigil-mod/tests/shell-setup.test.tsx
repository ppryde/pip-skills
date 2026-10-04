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
  expect(card.map(q => q.header)).toEqual(['🎚️ Nudge at', '🎛️Vigil bar', '🤖 Auto mode', '🌅Last light'])
  const answers = Object.fromEntries(card.map(q => [q.question, q.header.includes('Auto') ? 'On' : q.header.includes('Nudge') ? '50%' : 'Off']))
  const r = await $.tool.call(ask(card, answers) as never)
  const next = JSON.stringify((r as { context?: string[] }).context ?? [])
  expect(next).toContain('⏱️Idle time')
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
  expect(JSON.stringify((r as { context?: string[] }).context ?? [])).toContain('A one-line bar')
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
  await $.session.measure({ context: { window: 1_000_000, percent: 36 }, rateLimits: [], changed: ['context'] as never })
  await w.clock.settle()
  await $.tool.call({ tool: TOOL, tool_use_id: 'h', goal: 'G', state: 'S', next_step: 'N', session_name: 'Name' } as never)
  await w.clock.settle()
  expect(w.notices).toContain('🧹 Handing over in 30 s — send anything to cancel')
  await w.clock.advance(30_000)
  expect(w.commands).toContain('clear')
})

test('RC answered No: saved, and the unattended clear on the phone never runs', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await armOnPhone($ as never, w)
  const card = cardOf(w.submits.at(-1)?.text ?? '')
  await $.tool.call(ask(card, { [card[0]?.question ?? '']: 'No' }) as never)
  expect(w.store.get('settings')).toMatchObject({ rcAutoClear: 'no' })
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
