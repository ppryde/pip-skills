import { expect, test } from 'claude-code/testing'
import { V } from '../plugin/core/voice'
import { START, human, turn, world } from './world'

const MIN = 60_000
const HOUR = 60 * MIN
const TOOL = 'mcp__context-vigil-mod__vigil_handover'
const call = (extra: Record<string, unknown> = {}) => ({ tool: TOOL, tool_use_id: 'h1', goal: 'G', state: 'S', next_step: 'N', session_name: 'Name', ...extra })
const asks = (w: { submits: { text: string }[] }) => w.submits.filter(s => s.text.includes(TOOL)).length
const iso = (ms: number) => new Date(ms).toISOString()
const drop = (r: unknown) => (r as { drop?: string }).drop

test('"do a handover" runs the handover as /vho: dropped with a line, instruction, tool, clear, resume', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  const r = await $.prompt.submit(human('do a handover'))
  expect(drop(r)).toBe(V.handoverRequested)
  await w.clock.settle()
  expect(asks(w)).toBe(1)
  expect(w.submits.at(-1)?.origin).toBe('plugin')
  await $.tool.call(call() as never)
  await w.clock.settle()
  expect(w.commands).toContain('clear')
  w.sessionId.value = 's2'
  await $.classic.SessionStart({ source: 'clear' } as never)
  await w.clock.advance(500)
  expect(w.submits.at(-1)?.text).toContain('Resume from the handover')
})

test('the request is observed as a human act', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('handover'))
  expect(w.state.get('context-vigil-mod.mode')).toBe('attended')
})

test('talk about handovers goes through untouched', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  for (const text of ['how does the handover work', 'fix the handover bug', "don't hand over yet", 'no handover']) {
    const r = await $.prompt.submit(human(text))
    expect(drop(r)).toBeUndefined()
  }
  await w.clock.settle()
  expect(asks(w)).toBe(0)
})

test('only a human prompt is a request: a plugin or bridge-less origin is not', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  const r = await $.prompt.submit({ text: 'do a handover', wait: false, origin: { kind: 'plugin' } as never })
  expect(drop(r)).toBeUndefined()
  await w.clock.settle()
  expect(asks(w)).toBe(0)
})

test('from the phone it is still a human request', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  const r = await $.prompt.submit(human('hand this off', 'bridge'))
  expect(drop(r)).toBe(V.handoverRequested)
  await w.clock.settle()
  expect(asks(w)).toBe(1)
})

test('a second request while one is in flight says so and asks nothing more', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('handover'))
  await w.clock.settle()
  await $.prompt.submit(human('handover please'))
  await w.clock.settle()
  expect(asks(w)).toBe(1)
  expect(w.notices).toContain(V.handoverInProgress)
})

test('while the usage limit is latched the request waits and says so', async ($, on) => {
  const w = world(on, { now: 1_000_000 })
  w.rateLimits.value = [{ kind: 'five_hour', percentUsed: 100, resetsAt: iso(1_000_000 + HOUR) }]
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.classic.StopFailure({ error: 'rate_limit' } as never)
  await $.prompt.submit(human('do a handover'))
  await w.clock.settle()
  expect(asks(w)).toBe(0)
  expect(w.notices).toContain(V.waiting('latched'))
})

test('classic installed: the mod stands down and lets the words through', async ($, on) => {
  const w = world(on, { files: { '/cfg/settings.json': JSON.stringify({ hooks: { Stop: [{ hooks: [{ type: 'command', command: '"/s/context-vigil/scripts/context-vigil" hook stop' }] }] } }) } })
  await $.session.start(START)
  const r = await $.prompt.submit(human('do a handover'))
  expect(drop(r)).toBeUndefined()
  await w.clock.settle()
  expect(asks(w)).toBe(0)
})

test('the last-light hold comes first: the prompt is held, not turned into a handover', async ($, on) => {
  const w = world(on, { store: { settings: { lastLight: true, nudgeAt: 90 } } })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure({ context: { window: 1_000_000, percent: 30 }, rateLimits: [], changed: ['context'] as never })
  await $.turn.complete(turn())
  await w.clock.advance(55 * MIN)
  await $.tool.call({ tool: TOOL, tool_use_id: 'w', goal: 'G', state: 'S', next_step: 'N', session_name: 'Name' } as never)
  await $.turn.complete(turn('ll'))
  await w.clock.advance(70 * MIN)
  w.askAnswer.value = V.lastLightCarryOn
  const r = await $.prompt.submit(human('do a handover'))
  expect(drop(r)).toBe(V.heldForLastLight)
})

// The looser net: the tool itself, when the person's latest message mentioned a handover.
test('the model calls the tool after the person mentioned a handover: it clears and resumes like /vho', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('could you maybe do a handover when you reach a good stopping point in this work'))
  await $.tool.call(call() as never)
  await w.clock.settle()
  expect(w.commands).toContain('clear')
  w.sessionId.value = 's2'
  await $.classic.SessionStart({ source: 'clear' } as never)
  await w.clock.advance(500)
  expect(w.submits.at(-1)?.text).toContain('Resume from the handover')
})

test('a later message that does not mention it ends the permission: the call is volunteered, saved, never cleared', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('how does the handover work'))
  await $.prompt.submit(human('thanks, carry on'))
  await $.tool.call(call() as never)
  await w.clock.settle()
  expect(w.commands).not.toContain('clear')
  expect(w.notices.some(n => n.includes('not asked for'))).toBe(true)
})

test('the permission is spent by the call: a repeat is volunteered', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('please write a handoff when ready'))
  await $.tool.call(call() as never)
  await w.clock.settle()
  expect(w.commands.filter(c => c === 'clear')).toHaveLength(1)
  await $.tool.call(call({ tool_use_id: 'h2' }) as never)
  await w.clock.settle()
  expect(w.commands.filter(c => c === 'clear')).toHaveLength(1)
})

test('no human prompt mentioning a handover at all: today\'s volunteer behaviour', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.tool.call(call() as never)
  await w.clock.settle()
  expect(w.commands).not.toContain('clear')
})

test('a /clear wipes the mention', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('talk to me about handover'))
  w.sessionId.value = 's2'
  w.state.clear()   // what a clear does to $.state
  await $.tool.call(call() as never)
  await w.clock.settle()
  expect(w.commands).not.toContain('clear')
})

test('classic installed: a mention does not turn the model\'s call into a request', async ($, on) => {
  const w = world(on, { files: { '/cfg/settings.json': JSON.stringify({ hooks: { Stop: [{ hooks: [{ type: 'command', command: '"/s/context-vigil/scripts/context-vigil" hook stop' }] }] } }) } })
  await $.session.start(START)
  await $.prompt.submit(human('could you maybe do a handover when you reach a good stopping point in this work'))
  await $.tool.call(call() as never)
  await w.clock.settle()
  expect(w.commands).not.toContain('clear')
  expect((w.state.get('context-vigil-mod.pending') as { resume?: boolean } | undefined)?.resume ?? false).toBe(false)
})

test('a call that fulfils the mod\'s own ask also spends the mention', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('how does the handover work'))
  await $.command.run({ command: 'vho', args: '', origin: { kind: 'composer' } as never } as never)
  await w.clock.settle()
  await $.tool.call(call() as never)
  await w.clock.settle()
  expect(w.commands.filter(c => c === 'clear')).toHaveLength(1)
  await $.tool.call(call({ tool_use_id: 'h2' }) as never)
  await w.clock.settle()
  expect(w.commands.filter(c => c === 'clear')).toHaveLength(1)
  expect(w.notices.some(n => n.includes('not asked for'))).toBe(true)
})
