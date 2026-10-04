import { expect, test } from 'claude-code/testing'
import { START, human, turn, world } from './world'

const MIN = 60_000
const TOOL = 'mcp__context-vigil-mod__vigil_handover'
const call = (extra: Record<string, unknown> = {}) => ({ tool: TOOL, tool_use_id: 'h1', goal: 'G', state: 'S', next_step: 'N', session_name: 'Name', ...extra })
const measure = (percent: number) => ({ context: { window: 1_000_000, percent }, rateLimits: [], changed: ['context'] as never })
const vho = { command: 'vho', args: '', origin: { kind: 'composer' } as never } as never
const PENDING = 'context-vigil-mod.pending'

test('a requested handover: instruction → tool → file → clear → inject → resume', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.command.run(vho)
  await w.clock.settle()
  expect(w.submits.at(-1)?.text).toContain(TOOL)
  expect(w.submits.at(-1)?.origin).toBe('plugin')
  const r = await $.tool.call(call() as never)
  expect(String((r as { result?: unknown }).result)).toContain('/cfg/context-vigil-mod/handovers/s1-1.md')
  expect(w.files.get('/cfg/context-vigil-mod/handovers/s1-1.md')).toContain('## Goal')
  await w.clock.settle()
  expect(w.commands).toContain('clear')
  w.sessionId.value = 's2'
  const ss = await $.classic.SessionStart({ source: 'clear' } as never)
  expect(ss.additionalContext?.join('\n')).toContain('## Goal')
  await w.clock.advance(500)
  expect(w.submits.at(-1)?.text).toContain('Resume from the handover')
})

test('/vhandoff does the same as /vho', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run({ command: 'vhandoff', args: '', origin: { kind: 'composer' } as never } as never)
  await w.clock.settle()
  expect(w.submits.at(-1)?.text).toContain(TOOL)
})

test('bad tool input is denied so the model can retry', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run(vho)
  await w.clock.settle()
  const r = await $.tool.call(call({ state: '' }) as never)
  expect((r as { deny?: string }).deny).toContain('state')
})

test('no tool call: one retry, then a visible failure and no clear', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run(vho)
  await w.clock.settle()
  await $.turn.complete(turn('a'))
  await w.clock.settle()
  expect(w.submits.filter(s => s.text.includes(TOOL)).length).toBe(2)
  await $.turn.complete(turn('b'))
  await w.clock.settle()
  expect(w.notices).toContain("📜 Couldn't write a handover — nothing was cleared")
  expect(w.commands).not.toContain('clear')
})

test('a turn that ends before the instruction prompt was sent is not a missed attempt', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await $.session.start(START)
  await $.prompt.submit(human('go'))
  await w.clock.advance(31 * MIN)
  await $.tool.call({ tool: 'Bash', tool_use_id: 'b', command: 'ls' } as never)
  await $.session.measure(measure(36))      // arms the handover; the submit is still on its timer
  await $.turn.complete(turn('running'))    // the turn that was already running ends
  await w.clock.settle()
  expect(w.submits.filter(s => s.text.includes(TOOL)).length).toBe(1)
})

test('a draft in the box waits, then clears once it is gone', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run(vho)
  await w.clock.settle()
  w.draft.value = 'half a sen'
  await $.tool.call(call() as never)
  await w.clock.settle()
  expect(w.commands).not.toContain('clear')
  expect(w.notices).toContain('✍️ Handover waiting — there is a draft in your prompt box')
  w.draft.value = ''
  await w.clock.advance(2000)
  expect(w.commands).toContain('clear')
})

test('a refused /clear says so and keeps the handover pending', async ($, on) => {
  const w = world(on)
  w.clearRefused.value = true
  await $.session.start(START)
  await $.command.run(vho)
  await w.clock.settle()
  await $.tool.call(call() as never)
  await w.clock.settle()
  expect(w.notices).toContain('🧹 /clear was refused — the handover is still pending; /clear to resume from it')
  expect(w.state.get(PENDING)).toMatchObject({ path: '/cfg/context-vigil-mod/handovers/s1-1.md' })
})

test('auto mode at the threshold hands over by itself', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await $.session.start(START)
  await $.prompt.submit(human('go'))
  await w.clock.advance(31 * MIN)
  await $.turn.complete(turn())
  await $.session.measure(measure(36))
  await w.clock.settle()
  expect(w.submits.at(-1)?.text).toContain(TOOL)
})

test('clear resets lastNudged so the next crossing nudges again', async ($, on) => {
  const w = world(on, { store: { settings: { bar: false } } })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(36))
  expect(w.notices.filter(n => n.includes('Context at')).length).toBe(1)
  await $.classic.SessionStart({ source: 'clear' } as never)
  await $.session.measure(measure(5))
  await $.session.measure(measure(36))
  expect(w.notices.filter(n => n.includes('Context at')).length).toBe(2)
})

test('a pending handover is keyed by its session: offered to its own session only', async ($, on) => {
  const mine = { session: 's1', path: '/cfg/context-vigil-mod/handovers/s1-1.md', name: 'Mine', reason: 'request', markdown: '# MINE', resume: true, followUp: null, createdAt: 1 }
  const theirs = { ...mine, session: 'other', path: '/cfg/context-vigil-mod/handovers/other-1.md', name: 'Theirs', markdown: '# THEIRS' }
  const w = world(on, { store: { 'pending:s1': mine, 'pending:other': theirs } })
  await $.session.start(START)
  expect(w.notices.some(n => n.includes('s1-1.md'))).toBe(true)
  expect(w.notices.some(n => n.includes('other-1.md'))).toBe(false)
  const ss = await $.classic.SessionStart({ source: 'clear' } as never)
  expect(ss.additionalContext?.join('\n')).toContain('# MINE')
  expect(ss.additionalContext?.join('\n')).not.toContain('# THEIRS')
  w.sessionId.value = 'other'
  await $.session.start(START)
  expect(w.notices.some(n => n.includes('other-1.md'))).toBe(true)
  w.sessionId.value = 's1'
  w.notices.length = 0
  await $.session.start(START)
  expect(w.notices.some(n => n.includes('s1-1.md'))).toBe(false)
})

test('a consumed pending handover renames the new session before the resume submit', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run(vho)
  await w.clock.settle()
  await $.tool.call(call({ session_name: 'Fix the bar' }) as never)
  await w.clock.settle()
  w.commands.length = 0
  const before = w.submits.length
  w.sessionId.value = 's2'
  await $.classic.SessionStart({ source: 'clear' } as never)
  await w.clock.advance(0)
  expect(w.commands).toContain('rename')
  expect(w.renames).toEqual(['Fix the bar'])
  expect(w.submits.length).toBe(before)      // the resume submit is still on its 500 ms timer
  await w.clock.advance(500)
  expect(w.submits.at(-1)?.text).toContain('Resume from the handover')
})

test('a rejected rename still resumes, and says so', async ($, on) => {
  const w = world(on)
  w.renameRefused.value = true
  await $.session.start(START)
  await $.command.run(vho)
  await w.clock.settle()
  await $.tool.call(call() as never)
  await w.clock.settle()
  w.sessionId.value = 's2'
  await $.classic.SessionStart({ source: 'clear' } as never)
  await w.clock.advance(500)
  expect(w.notices).toContain("🏷️ couldn't name the new session — carrying on")
  expect(w.submits.at(-1)?.text).toContain('Resume from the handover')
})

test('a stored handover with no name resumes without any rename', async ($, on) => {
  const old = { session: 's1', path: '/cfg/context-vigil-mod/handovers/s1-1.md', reason: 'request', markdown: '# OLD', resume: true, followUp: null, createdAt: 1 }
  const w = world(on, { store: { 'pending:s1': old } })
  await $.session.start(START)
  await $.classic.SessionStart({ source: 'clear' } as never)
  await w.clock.advance(500)
  expect(w.commands).not.toContain('rename')
  expect(w.notices.some(n => n.includes('couldn'))).toBe(false)
  expect(w.submits.at(-1)?.text).toContain('Resume from the handover')
})
