import { expect, test } from 'claude-code/testing'
import { START, human, world } from './world'

const TOOL = 'mcp__context-vigil-mod__vigil_handover'
const HOUR = 3_600_000
const iso = (ms: number) => new Date(ms).toISOString()
const measure = (rateLimits: { kind: string; percentUsed: number; resetsAt?: string }[], percent = 10) =>
  ({ context: { window: 1_000_000, percent }, rateLimits, changed: ['rateLimits'] as never })
const asks = (w: { submits: { text: string }[] }) => w.submits.filter(s => s.text.includes(TOOL)).length
const write = { tool: TOOL, tool_use_id: 'h', goal: 'G', state: 'S', next_step: 'N', session_name: 'Name' } as never

test('while latched nothing is submitted or cleared; at the lift the deferred handover runs', async ($, on) => {
  const w = world(on, { now: 1_000_000 })
  w.rateLimits.value = [{ kind: 'five_hour', percentUsed: 100, resetsAt: iso(1_000_000 + HOUR) }]
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.classic.StopFailure({ error: 'rate_limit' } as never)
  expect(w.notices.some(n => n.startsWith('⏳ Usage limit reached — resumes'))).toBe(true)
  await $.command.run({ command: 'vho', args: '', origin: { kind: 'composer' } as never } as never)
  await w.clock.settle()
  expect(asks(w)).toBe(0)
  expect(w.notices).toContain('⏳ Handover waiting — the usage limit is in force')
  await w.clock.advance(HOUR + 1000)
  await $.session.measure(measure([{ kind: 'five_hour', percentUsed: 1, resetsAt: iso(1_000_000 + 6 * HOUR) }]))
  await w.clock.settle()
  expect(w.notices).toContain('⏳ Usage limit lifted — back to normal')
  expect(asks(w)).toBe(1)
  await $.tool.call(write)
  await w.clock.settle()
  expect(w.commands).toContain('clear')
})

test('a clear parked by the latch goes ahead when it lifts', async ($, on) => {
  const w = world(on, { now: 1_000_000 })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.command.run({ command: 'vho', args: '', origin: { kind: 'composer' } as never } as never)
  await w.clock.settle()
  w.rateLimits.value = [{ kind: 'five_hour', percentUsed: 100, resetsAt: iso(1_000_000 + HOUR) }]
  await $.classic.StopFailure({ error: 'rate_limit' } as never)   // latched between instruction and write
  await $.tool.call(write)
  await w.clock.settle()
  expect(w.commands).not.toContain('clear')
  await w.clock.advance(HOUR + 2000)                             // the latch's own timer lifts it at resetsAt
  expect(w.commands).toContain('clear')
})

test('seven_day at the trigger: handover once per window, then one resume after the reset', async ($, on) => {
  const w = world(on, { now: 1_000_000 })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  const resetsAt = iso(1_000_000 + 3 * HOUR)
  await $.session.measure(measure([{ kind: 'seven_day', percentUsed: 96, resetsAt }]))
  await w.clock.settle()
  expect(asks(w)).toBe(1)
  await $.session.measure(measure([{ kind: 'seven_day', percentUsed: 97, resetsAt }]))
  await w.clock.settle()
  expect(asks(w)).toBe(1)
  await $.tool.call(write)
  await w.clock.settle()
  expect(w.commands).not.toContain('clear')
  await w.clock.advance(3 * HOUR + 300_000)
  expect(w.submits.at(-1)?.text).toContain('limit has reset')
  expect(w.submits.filter(s => s.text.includes('limit has reset')).length).toBe(1)
  expect(w.state.get('context-vigil-mod.pending')).toBe(null)
})

test('a rejected limit resume is announced and logged, not swallowed', async ($, on) => {
  const w = world(on, { now: 1_000_000 })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure([{ kind: 'seven_day', percentUsed: 96, resetsAt: iso(1_000_000 + HOUR) }]))
  await w.clock.settle()
  w.submitRefused.value = true
  await w.clock.advance(HOUR + 300_000)
  expect(w.notices).toContain("📜 Couldn't write a handover — nothing was cleared")
  expect([...w.files.values()].some(t => t.includes('submit-rejected'))).toBe(true)
})

test('configured trigger and windows: below or unwatched does nothing; the watched window at its trigger fires', async ($, on) => {
  const w = world(on, { store: { settings: { limitPct: 98, limitWindows: ['spend_limit'] } } })
  await $.session.start(START)
  await $.session.measure(measure([{ kind: 'seven_day', percentUsed: 99, resetsAt: iso(5 * HOUR) }, { kind: 'spend_limit', percentUsed: 97, resetsAt: iso(5 * HOUR) }]))
  await w.clock.settle()
  expect(asks(w)).toBe(0)
  await $.session.measure(measure([{ kind: 'spend_limit', percentUsed: 98, resetsAt: iso(5 * HOUR) }]))
  await w.clock.settle()
  expect(asks(w)).toBe(1)
})
