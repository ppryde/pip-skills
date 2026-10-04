import { expect, test } from 'claude-code/testing'
import { START, human, turn, world } from './world'

const MIN = 60_000
const TOOL = 'mcp__context-vigil-mod__vigil_handover'
const measure = (percent: number) => ({ context: { window: 1_000_000, percent }, rateLimits: [], changed: ['context'] as never })
const write = { tool: TOOL, tool_use_id: 'h', goal: 'G', state: 'S', next_step: 'N', session_name: 'Name' } as never
const LL = { store: { settings: { lastLight: true, nudgeAt: 90 } } }
const asks = (w: { submits: { text: string }[] }) => w.submits.filter(s => s.text.includes(TOOL)).length
const ARMED = 'context-vigil-mod.lastLightArmed'
const PENDING = 'context-vigil-mod.pending'

test('fires at TTL − lead with both idle and context ≥ threshold; writes only, no clear', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())
  await w.clock.advance(54 * MIN)
  expect(asks(w)).toBe(0)
  await w.clock.advance(1 * MIN)
  expect(asks(w)).toBe(1)
  expect(w.submits.at(-1)?.text).toContain('Do not clear')
  await $.tool.call(write)
  await w.clock.settle()
  expect(w.notices).toContain('🌅 Last light: a handover is ready 📜 — carry on as normal, or /clear to resume from it ✨')
  expect(w.commands).not.toContain('clear')
})

test('loop guard: without a human prompt it never fires again; a human prompt re-arms it', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())
  await w.clock.advance(55 * MIN)
  await $.tool.call(write)
  await $.classic.SessionStart({ source: 'clear' } as never)   // pending consumed, still no human prompt
  await $.session.measure(measure(30))
  await $.turn.complete(turn('ll'))                              // its own turn refreshed the cache
  await w.clock.advance(60 * MIN)
  expect(asks(w)).toBe(1)                                        // disarmed — not blocked by pending
  await $.prompt.submit(human('back'))
  await $.turn.complete(turn('after'))
  await w.clock.advance(55 * MIN)
  expect(asks(w)).toBe(2)
})

test('below the threshold it does not fire; at the threshold it does', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(24))
  await $.turn.complete(turn())
  await w.clock.advance(56 * MIN)
  expect(asks(w)).toBe(0)
  await $.prompt.submit(human('more'))
  await $.session.measure(measure(25))
  await $.turn.complete(turn('2'))
  await w.clock.advance(56 * MIN)
  expect(asks(w)).toBe(1)
})

test('switched off it never fires', async ($, on) => {
  const w = world(on, { store: { settings: { lastLight: false, nudgeAt: 90 } } })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())
  await w.clock.advance(56 * MIN)
  expect(asks(w)).toBe(0)
  expect(w.submits.map(s => s.text)).toEqual(['hi'])
})

test('on return after expiry the prompt is held and the choice asked; resume carries it over', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())
  await w.clock.advance(55 * MIN)
  await $.tool.call(write)
  await $.turn.complete(turn('ll'))
  await w.clock.advance(70 * MIN)
  w.askAnswer.value = 'Resume from handover'
  const r = await $.prompt.submit(human('morning!'))
  expect((r as { drop?: string }).drop).toBeDefined()
  await w.clock.settle()
  expect(w.commands).toContain('clear')
  await $.classic.SessionStart({ source: 'clear' } as never)
  await w.clock.advance(500)
  expect(w.submits.at(-1)?.text).toBe('morning!')
  expect(w.state.get(ARMED)).toBe(true)
})

test('carry on submits the held prompt unchanged into the same conversation', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())
  await w.clock.advance(55 * MIN)
  await $.tool.call(write)
  await $.turn.complete(turn('ll'))
  await w.clock.advance(70 * MIN)
  w.askAnswer.value = 'Carry on'
  await $.prompt.submit(human('morning!'))
  await w.clock.settle()
  expect(w.submits.at(-1)?.text).toBe('morning!')
  expect(w.commands).not.toContain('clear')
  expect(w.state.get(PENDING)).toBe(null)
})

test('a dismissed question carries on, so the held prompt is never lost', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())
  await w.clock.advance(55 * MIN)
  await $.tool.call(write)
  await $.turn.complete(turn('ll'))
  await w.clock.advance(70 * MIN)
  w.askAnswer.value = null
  await $.prompt.submit(human('morning!'))
  await w.clock.settle()
  expect(w.submits.at(-1)?.text).toBe('morning!')
})

test('a 1-hour cache fires; a switch to a 5-minute cache cancels the scheduled fire', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())                                  // schedules the 1 h fire
  await $.classic.PostModelSwitch({ cache_ttl: '5m' } as never)  // must cancel it
  await w.clock.advance(120 * MIN)
  expect(asks(w)).toBe(0)
  await $.classic.PostModelSwitch({ cache_ttl: '1h' } as never)  // that cache is long cold: no catch-up fire
  await w.clock.settle()
  expect(asks(w)).toBe(0)
  await $.prompt.submit(human('again'))
  await $.turn.complete(turn('2'))
  await w.clock.advance(55 * MIN)
  expect(asks(w)).toBe(1)
})
