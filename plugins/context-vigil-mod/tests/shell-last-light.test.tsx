import { expect, test } from 'claude-code/testing'
import { START, human, readTurn, turn, world, type World } from './world'
import { V } from '../core/voice'

const MIN = 60_000
const TOOL = 'mcp__context-vigil-mod__vigil_handover'
const measure = (percent: number) => ({ context: { window: 1_000_000, percent }, rateLimits: [], changed: ['context'] as never })
const write = { tool: TOOL, tool_use_id: 'h', goal: 'G', state: 'S', next_step: 'N', session_name: 'Name' } as never
const LL = { store: { settings: { lastLight: true, nudgeAt: 90 } } }
const asks = (w: { submits: { text: string }[] }) => w.submits.filter(s => s.text.includes(TOOL)).length
const PENDING = 'context-vigil-mod.pending'
const eventLog = (w: World) => [...w.files.entries()].find(([k]) => k.includes('/events/'))?.[1] ?? ''
const count = (text: string, needle: string) => text.split(needle).length - 1
const TTL = 'context-vigil-mod.cacheTtl'

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
  w.sessionId.value = 's2'
  const ss = await $.classic.SessionStart({ source: 'clear' } as never)
  expect(w.state.get(PENDING)).toBeUndefined()                   // $.state wiped by the clear
  expect(ss.additionalContext?.join('\n')).toContain('## Goal')  // the handover still crossed it
  await w.clock.advance(500)
  expect(w.submits.at(-1)?.text).toBe('morning!')
  // The held prompt was the person's return: last light stays armed across the wipe.
  await $.session.measure(measure(30))
  await $.turn.complete(turn('morning'))
  await w.clock.advance(55 * MIN)
  expect(asks(w)).toBe(2)
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
  await w.clock.settle()
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
  expect(eventLog(w)).toContain('"source":"post-switch"')
})

test('a 5-minute cache never fires, and says why once', async ($, on) => {
  const w = world(on, LL)
  w.cacheWrites.value = { h1: 0, m5: 100 }
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())
  await w.clock.settle()
  await $.prompt.submit(human('more'))
  await $.turn.complete(turn('2'))
  await w.clock.advance(120 * MIN)
  expect(asks(w)).toBe(0)
  expect(w.state.get(TTL)).toBe('5m')
  expect(count(eventLog(w), '"reason":"ttl-5m"')).toBe(1)
  expect(count(eventLog(w), '"kind":"cache.ttl"')).toBe(1)
})

test('an unknown cache never fires: nothing assumes 1 hour', async ($, on) => {
  const w = world(on, LL)
  w.cacheWrites.value = 'fail'
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())
  await w.clock.advance(120 * MIN)
  expect(asks(w)).toBe(0)
  expect(w.state.get(TTL) ?? 'unknown').toBe('unknown')
  expect(eventLog(w)).toContain('"reason":"ttl-unknown"')
})

test('the lifetime can drop mid-session with no model switch (usage credits): the pending fire is cancelled', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())
  await w.clock.settle()
  expect(w.state.get(TTL)).toBe('1h')
  await w.clock.advance(10 * MIN)
  w.cacheWrites.value = { h1: 0, m5: 300 }
  await $.prompt.submit(human('more'))
  await $.turn.complete(turn('2'))
  await w.clock.advance(120 * MIN)
  expect(asks(w)).toBe(0)
  expect(eventLog(w)).toContain('"from":"1h"')
  expect(eventLog(w)).toContain('"source":"response"')
})

test('a pure cache read costs no transcript read and keeps the lifetime', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())
  await w.clock.settle()
  const tails = w.tails.length
  await $.turn.complete(readTurn('2'))
  await w.clock.settle()
  expect(w.tails.length).toBe(tails)
  expect(w.state.get(TTL)).toBe('1h')
  await w.clock.advance(55 * MIN)
  expect(asks(w)).toBe(1)
})

test('a subagent turn says nothing about the main conversation\'s cache', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.turn.complete({ ...turn(), agentId: 'sub' } as never)
  await w.clock.settle()
  expect(w.tails.length).toBe(0)
})

test('a /clear starts the new session unknown until its first response says otherwise', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.turn.complete(turn())
  await w.clock.settle()
  expect(w.state.get(TTL)).toBe('1h')
  await $.classic.SessionStart({ source: 'clear' } as never)
  expect(w.state.get(TTL) ?? 'unknown').toBe('unknown')
})

test('the transcript is read from the path the session reported', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.classic.SessionStart({ source: 'startup', transcript_path: '/t/s1.jsonl' } as never)
  await $.turn.complete(turn())
  await w.clock.settle()
  expect(w.tails.at(-1)?.at(-1)).toBe('/t/s1.jsonl')
})

test('without a reported path the transcript is found by the project folder convention', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.turn.complete(turn())
  await w.clock.settle()
  expect(w.tails.at(-1)?.at(-1)).toBe('/cfg/projects/-repo/s1.jsonl')
})

test('a model switch is read before it happens too (PreModelSwitch)', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.classic.PreModelSwitch({ cache_ttl: '5m' } as never)
  expect(w.state.get(TTL)).toBe('5m')
  expect(eventLog(w)).toContain('"source":"pre-switch"')
})

test('an unknown lifetime claims no cold-cache cost: the returning human is not held', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())
  await w.clock.advance(55 * MIN)
  await $.tool.call(write)
  w.state.set(TTL, 'unknown')
  await w.clock.advance(70 * MIN)
  const held = await $.prompt.submit(human('back'))
  expect(held).not.toEqual({ drop: V.heldForLastLight })
})

test('a returning human is held against the real expiry: a 5-minute cache expires in 5 minutes', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())
  await w.clock.advance(55 * MIN)
  await $.tool.call(write)                        // last-light handover pending, written under a 1 h cache
  await $.turn.complete(turn('ll'))
  w.cacheWrites.value = { h1: 0, m5: 10 }         // credits ran out: the latest response wrote 5m
  await $.turn.complete(turn('ll2'))
  await w.clock.advance(6 * MIN)
  w.askAnswer.value = null
  const held = await $.prompt.submit(human('back'))
  await w.clock.settle()
  expect(held).toEqual({ drop: V.heldForLastLight })   // 6 min on a 5-minute cache is cold; on an unknown one it would not be claimed
  expect(w.submits.at(-1)?.text).toBe('back')          // asked, dismissed → carried on
})

test('a hot reload re-arms last light from the last turn', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())
  await w.clock.advance(10 * MIN)
  await $.session.start(START)          // the reload cancels the scheduled fire
  await w.clock.advance(45 * MIN)
  expect(asks(w)).toBe(1)
})

async function heldReturn($: any, w: ReturnType<typeof world>, answer: string) {
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())
  await w.clock.advance(55 * MIN)
  await $.tool.call(write)
  await $.turn.complete(turn('ll'))
  await w.clock.advance(70 * MIN)
  w.askAnswer.value = answer
}

test('a rejected follow-up after a resume clear keeps the held message visible', async ($, on) => {
  const w = world(on, LL)
  await heldReturn($, w, 'Resume from handover')
  await $.prompt.submit(human('morning!'))
  await w.clock.settle()
  w.sessionId.value = 's2'
  await $.classic.SessionStart({ source: 'clear' } as never)
  w.submitRefused.value = true
  await w.clock.advance(500)
  expect(w.notices.some(n => n.includes("Couldn't resume") && n.includes('morning!') && n.includes('/handovers/s1-1.md'))).toBe(true)
})

test('a rejected carry-on submit keeps the held message visible', async ($, on) => {
  const w = world(on, LL)
  await heldReturn($, w, 'Carry on')
  w.submitRefused.value = true
  await $.prompt.submit(human('morning!')).catch(() => null)
  await w.clock.settle()
  expect(w.notices.some(n => n.includes("Couldn't resume") && n.includes('morning!'))).toBe(true)
})

test('the held prompt is dropped with a voice string', async ($, on) => {
  const w = world(on, LL)
  await heldReturn($, w, 'Carry on')
  const r = await $.prompt.submit(human('morning!'))
  expect((r as { drop?: string }).drop).toBe(V.heldForLastLight)
})
