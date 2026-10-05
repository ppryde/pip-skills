import { expect, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import { START, human, turn, world, type World } from './world'

const TOOL = 'mcp__context-vigil-mod__vigil_handover'
const HOUR = 3_600_000
const iso = (ms: number) => new Date(ms).toISOString()
const measure = (rateLimits: { kind: string; percentUsed: number; resetsAt?: string }[], percent = 10) =>
  ({ context: { window: 1_000_000, percent }, rateLimits, changed: ['rateLimits'] as never })
const asks = (w: { submits: { text: string }[] }) => w.submits.filter(s => s.text.includes(TOOL)).length
const write = { tool: TOOL, tool_use_id: 'h', goal: 'G', state: 'S', next_step: 'N', session_name: 'Name' } as never

test('while latched nothing is submitted or cleared; at the lift the deferred handover runs', async ($, on) => {
  const w = world(on, { now: 1_000_000, store: { settings: { auto: true } } })
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

// A clear parked on the latch (R2-01): the latch lands between the instruction and the write.
async function parkedOnLatch($: Engine, w: World, opts: { turnAfterWrite?: boolean } = {}) {
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.turn.complete(turn('before'))
  await $.command.run({ command: 'vho', args: '', origin: { kind: 'composer' } as never } as never)
  await w.clock.settle()
  w.rateLimits.value = [{ kind: 'five_hour', percentUsed: 100, resetsAt: iso(1_000_000 + HOUR) }]
  await $.classic.StopFailure({ error: 'rate_limit' } as never)   // latched between instruction and write
  await $.tool.call(write)
  await w.clock.settle()
  expect(w.commands).not.toContain('clear')
  if (opts.turnAfterWrite) { await w.clock.advance(5 * 60_000); await $.turn.complete(turn('after')) }
}
const parkedDropped = (w: World) => [...w.files.entries()].find(([k]) => k.includes('/events/'))?.[1].includes('"parked-dropped"') ?? false

test('a clear parked by the latch, auto Off, is offered at the lift — never run (R2-01)', async ($, on) => {
  const w = world(on, { now: 1_000_000 })
  await parkedOnLatch($, w)
  await w.clock.advance(HOUR + 2000)                             // the latch's own timer lifts it at resetsAt
  expect(w.commands).not.toContain('clear')
  expect(w.notices.some(n => n.startsWith('📜 A handover is waiting'))).toBe(true)
  expect(parkedDropped(w)).toBe(true)
  expect(w.state.get('context-vigil-mod.pending')).not.toBe(null)
})

test('a clear parked by the latch, auto On and the person still away, runs at the lift as unattended (R2-01)', async ($, on) => {
  const w = world(on, { now: 1_000_000, store: { settings: { auto: true } } })
  await parkedOnLatch($, w)
  await w.clock.advance(HOUR + 2000)
  expect(w.commands).toContain('clear')
})

test('a person who returns while a clear is parked on the latch turns it into an offer (R2-01)', async ($, on) => {
  const w = world(on, { now: 1_000_000, store: { settings: { auto: true } } })
  await parkedOnLatch($, w)
  w.notices.length = 0
  await $.prompt.submit(human('carry on'))
  expect(w.notices.some(n => n.startsWith('📜 A handover is waiting'))).toBe(true)
  await $.turn.complete(turn('mine'))
  await w.clock.advance(HOUR + 2000)
  expect(w.commands).not.toContain('clear')
  expect(w.state.get('context-vigil-mod.pending')).not.toBe(null)
})

test('a clear parked by the latch is offered, not run, when a turn has run since the write (R2-01)', async ($, on) => {
  const w = world(on, { now: 1_000_000, store: { settings: { auto: true } } })
  await parkedOnLatch($, w, { turnAfterWrite: true })
  await w.clock.advance(HOUR + 2000)
  expect(w.commands).not.toContain('clear')
  expect(w.notices.some(n => n.startsWith('📜 A handover is waiting'))).toBe(true)
  expect(parkedDropped(w)).toBe(true)
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

test('a latch set before a clear still holds after it: no handover, no limit resume', async ($, on) => {
  const w = world(on, { now: 1_000_000 })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure([{ kind: 'seven_day', percentUsed: 96, resetsAt: iso(1_000_000 + HOUR) }]))
  await w.clock.settle()
  expect(asks(w)).toBe(1)
  await $.tool.call(write)
  w.rateLimits.value = [{ kind: 'five_hour', percentUsed: 100, resetsAt: iso(1_000_000 + 10 * HOUR) }]
  await $.classic.StopFailure({ error: 'rate_limit' } as never)
  w.sessionId.value = 's2'
  await $.classic.SessionStart({ source: 'clear' } as never)
  await $.command.run({ command: 'vho', args: '', origin: { kind: 'composer' } as never } as never)
  await w.clock.settle()
  expect(asks(w)).toBe(1)
  expect(w.notices).toContain('⏳ Handover waiting — the usage limit is in force')
  await w.clock.advance(HOUR + 600_000)                          // past the seven_day resume time
  expect(w.submits.some(s => s.text.includes('limit has reset'))).toBe(false)
})

test('an early stop fired before a clear does not fire again after it for the same window', async ($, on) => {
  const w = world(on, { now: 1_000_000 })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  const resetsAt = iso(1_000_000 + 3 * HOUR)
  await $.session.measure(measure([{ kind: 'seven_day', percentUsed: 96, resetsAt }]))
  await w.clock.settle()
  await $.tool.call(write)
  w.sessionId.value = 's2'
  await $.classic.SessionStart({ source: 'clear' } as never)
  await $.session.measure(measure([{ kind: 'seven_day', percentUsed: 97, resetsAt }]))
  await w.clock.settle()
  expect(asks(w)).toBe(1)
})

test('a latch lifted by another session still drains this one: the deferred handover runs', async ($, on) => {
  const w = world(on, { now: 1_000_000, store: { settings: { auto: true } } })
  w.rateLimits.value = [{ kind: 'five_hour', percentUsed: 100, resetsAt: iso(1_000_000 + HOUR) }]
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.classic.StopFailure({ error: 'rate_limit' } as never)
  await $.command.run({ command: 'vho', args: '', origin: { kind: 'composer' } as never } as never)
  await w.clock.settle()
  expect(asks(w)).toBe(0)
  expect(w.store.get('latch')).toBeDefined()
  w.store.delete('latch')                                        // the other process lifted it
  await w.clock.advance(31 * 60_000)                             // the person has long since gone quiet
  await $.session.measure(measure([]))
  await w.clock.settle()
  expect(asks(w)).toBe(1)
})

test('with no latch, a measure does not retry a clear parked for another reason', async ($, on) => {
  const w = world(on, { now: 1_000_000 })
  w.clearRefused.value = true
  await $.session.start(START)
  await $.command.run({ command: 'vho', args: '', origin: { kind: 'composer' } as never } as never)
  await w.clock.settle()
  await $.tool.call(write)
  await w.clock.settle()
  await $.session.measure(measure([]))
  await w.clock.settle()
  expect(w.notices.filter(n => n.startsWith('🧹 /clear was refused')).length).toBe(1)
})

test('a stale latch left in the store is lifted at session start', async ($, on) => {
  const w = world(on, { now: 1_000_000 + 2 * HOUR, store: { latch: { kind: 'five_hour', resetsAtMs: 1_000_000 } } })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.command.run({ command: 'vho', args: '', origin: { kind: 'composer' } as never } as never)
  await w.clock.settle()
  expect(asks(w)).toBe(1)
})

test('the limit resume names the handover file even after a clear consumed it', async ($, on) => {
  const w = world(on, { now: 1_000_000 })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure([{ kind: 'seven_day', percentUsed: 96, resetsAt: iso(1_000_000 + HOUR) }]))
  await w.clock.settle()
  await $.tool.call(write)
  w.sessionId.value = 's2'
  await $.classic.SessionStart({ source: 'clear' } as never)
  await w.clock.advance(HOUR + 300_000)
  const resume = w.submits.find(s => s.text.includes('limit has reset'))
  expect(resume?.text).toContain('/cfg/context-vigil-mod/handovers/s1-1.md')
  expect(resume?.text).not.toContain('(no file)')
})

test('a rejected limit resume is announced and logged, not swallowed', async ($, on) => {
  const w = world(on, { now: 1_000_000 })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure([{ kind: 'seven_day', percentUsed: 96, resetsAt: iso(1_000_000 + HOUR) }]))
  await w.clock.settle()
  w.submitRefused.value = true
  await w.clock.advance(HOUR + 300_000)
  expect(w.notices.some(n => n.includes("Couldn't resume"))).toBe(true)
  expect(w.notices).not.toContain("📜 Couldn't write a handover — nothing was cleared")
  expect([...w.files.values()].some(t => t.includes('submit-rejected'))).toBe(true)
})

test('a refused limit resume clears the job: the next early stop is judged on its own stop time and file (R3-05)', async ($, on) => {
  const w = world(on, { now: 1_000_000 })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure([{ kind: 'seven_day', percentUsed: 96, resetsAt: iso(1_000_000 + HOUR) }]))
  await w.clock.settle()
  await $.tool.call(write)
  await w.clock.settle()
  w.submitRefused.value = true
  await w.clock.advance(HOUR + 300_000)
  expect(w.notices.some(n => n.includes("Couldn't resume"))).toBe(true)
  w.submitRefused.value = false
  const first = [...w.files.keys()].filter(p => p.includes('/handovers/'))
  await $.prompt.submit(human('back at the desk'))
  await w.clock.advance(60_000)
  const resetsAt = iso(1_000_000 + 4 * HOUR)
  await $.session.measure(measure([{ kind: 'seven_day', percentUsed: 97, resetsAt }]))
  await w.clock.settle()
  await $.tool.call({ ...(write as object), tool_use_id: 'h2' } as never)
  await w.clock.settle()
  await w.clock.advance(4 * HOUR)
  const r = resumes(w)
  expect(r.length).toBe(1)
  for (const p of first) expect(r[0]!.text).not.toContain(p)
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

// R1-09: a handover deferred by the latch is re-validated when it drains.
const MIN = 60_000
const vho = { command: 'vho', args: '', origin: { kind: 'composer' } as never } as never
async function latchedVho($: Engine, w: ReturnType<typeof world>, origin: 'composer' | 'bridge' = 'composer') {
  await $.session.start(START)
  await $.prompt.submit(human('hi', origin))
  w.rateLimits.value = [{ kind: 'five_hour', percentUsed: 100, resetsAt: iso(1_000_000 + HOUR) }]
  await $.classic.StopFailure({ error: 'rate_limit' } as never)
  await $.command.run(vho)
  await w.clock.settle()
  expect(w.store.get('latch')).toBeDefined()
  expect(w.state.get('context-vigil-mod.deferred')).toMatchObject({ reason: 'request' })
}
const lift = [{ kind: 'five_hour', percentUsed: 1, resetsAt: iso(1_000_000 + 6 * HOUR) }]

test('R1-09: a person who comes back cancels the deferred handover', async ($, on) => {
  const w = world(on, { now: 1_000_000, store: { settings: { auto: true } } })
  await latchedVho($, w)
  await $.prompt.submit(human('x', 'bridge'))
  expect(w.state.get('context-vigil-mod.deferred')).toBeNull()
  expect(w.notices.some(n => n.includes('was not run'))).toBe(true)
  await w.clock.advance(HOUR + 1000)
  await $.session.measure(measure(lift))
  await w.clock.settle()
  expect(asks(w)).toBe(0)
})

test('R1-09: a drained request runs as an unattended handover: RC gate, never a bare clear', async ($, on) => {
  const w = world(on, { now: 1_000_000, store: { settings: { auto: true } } })
  await latchedVho($, w, 'bridge')
  await w.clock.advance(HOUR + 1000)
  await $.session.measure(measure(lift))
  await w.clock.settle()
  expect(asks(w)).toBe(1)
  await $.tool.call(write)
  await w.clock.settle()
  expect(w.commands).not.toContain('clear')
  expect(w.notices.some(n => n.includes('not switched on'))).toBe(true)
})

test('R3-06: a hot reload offers a latch-drained unattended request, it never runs it as an attended clear', async ($, on) => {
  const w = world(on, { now: 1_000_000, store: { settings: { auto: true } } })
  await latchedVho($, w, 'bridge')
  await w.clock.advance(HOUR + 1000)
  await $.session.measure(measure(lift))
  await w.clock.settle()
  await $.tool.call(write)
  await w.clock.settle()
  expect(w.commands).not.toContain('clear')
  expect(w.notices.some(n => n.includes('not switched on'))).toBe(true)
  w.notices.length = 0
  await $.session.start(START)   // the hot reload: $.state kept the parked pending, the timers are gone
  await w.clock.settle()
  expect(w.commands).not.toContain('clear')
  expect(w.notices.length).toBeGreaterThan(0)
})

test('R1-09: with auto off a drained request is dropped with a notice', async ($, on) => {
  const w = world(on, { now: 1_000_000 })
  await latchedVho($, w)
  await w.clock.advance(HOUR + 1000)
  await $.session.measure(measure(lift))
  await w.clock.settle()
  expect(asks(w)).toBe(0)
  expect(w.notices.some(n => n.includes('was not run'))).toBe(true)
})

test('R1-09: the tool handler honours Awaiting.unattended for the attended re-check', async ($, on) => {
  const w = world(on, { now: 1_000_000, store: { settings: { auto: true } } })
  await $.session.start(START)
  w.state.set('context-vigil-mod.awaiting', { reason: 'request', resume: true, attempts: 1, started: true, unattended: true })
  await $.prompt.submit(human('i am here'))
  await $.tool.call(write)
  await w.clock.settle()
  expect(w.commands).not.toContain('clear')
  expect(w.notices.some(n => n.includes('you came back'))).toBe(true)
})

// R1-12: one resume chain per process; nothing sent over a person who has come back; a null path has its own text.
const stop = async ($: Engine, w: ReturnType<typeof world>, hours = 3) => {
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure([{ kind: 'seven_day', percentUsed: 96, resetsAt: iso(1_000_000 + hours * HOUR) }]))
  await w.clock.settle()
  await $.tool.call(write)
  await w.clock.settle()
}
const resumes = (w: { submits: { text: string }[] }) => w.submits.filter(s => s.text.includes('limit has reset'))

test('R1-12: two windows over the trigger give one resume prompt', async ($, on) => {
  const w = world(on, { now: 1_000_000 })
  await stop($, w)
  await $.session.measure(measure([{ kind: 'spend_limit', percentUsed: 97, resetsAt: iso(1_000_000 + 4 * HOUR) }]))
  await w.clock.settle()
  await w.clock.advance(5 * HOUR)
  expect(resumes(w)).toHaveLength(1)
})

test('R1-12: a message from the person since the stop means no resume prompt, a notice instead', async ($, on) => {
  const w = world(on, { now: 1_000_000 })
  await stop($, w)
  await w.clock.advance(HOUR)
  await $.prompt.submit(human('back already'))
  await w.clock.advance(3 * HOUR)
  expect(resumes(w)).toHaveLength(0)
  expect(w.notices.some(n => n.includes('you are back') && n.includes('s1-1.md'))).toBe(true)
})

test('R1-12: a draft in the box at resume time means no resume prompt', async ($, on) => {
  const w = world(on, { now: 1_000_000 })
  await stop($, w)
  await w.clock.advance(3 * HOUR)
  w.draft.value = 'half a thought'
  await w.clock.advance(300_000)
  expect(resumes(w)).toHaveLength(0)
  expect(w.notices.some(n => n.includes('you are back'))).toBe(true)
})

test('R1-12: no handover file means the resume says so, never "(no file)"', async ($, on) => {
  const w = world(on, { now: 1_000_000 })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure([{ kind: 'seven_day', percentUsed: 96, resetsAt: iso(1_000_000 + HOUR) }]))
  await w.clock.settle()
  await w.clock.advance(HOUR + 300_000)
  const r = resumes(w)[0]
  expect(r?.text).toContain('No handover was written')
  expect(r?.text).not.toContain('(no file)')
})

test('an idle session lifts and resumes after a latch another session left behind (R2-04)', async ($, on) => {
  const w = world(on, { now: 1_000_000, store: { latch: { kind: 'five_hour', resetsAtMs: 1_000_000 + 2 * HOUR } } })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure([{ kind: 'seven_day', percentUsed: 96, resetsAt: iso(1_000_000 + HOUR) }]))
  await w.clock.settle()
  await w.clock.advance(2 * HOUR + 600_000)           // past the foreign latch's reset: no measure arrives
  expect(w.store.get('latch')).toBeUndefined()
  expect(w.submits.some(s => s.text.includes('limit has reset'))).toBe(true)
})

test('a latch another session set is lifted by this one\'s own timer at its reset (R2-04)', async ($, on) => {
  const w = world(on, { now: 1_000_000, store: { latch: { kind: 'five_hour', resetsAtMs: 1_000_000 + HOUR } } })
  await $.session.start(START)
  await $.session.measure(measure([{ kind: 'five_hour', percentUsed: 100, resetsAt: iso(1_000_000 + HOUR) }]))
  await w.clock.advance(HOUR + 2000)                  // no further measure
  expect(w.store.get('latch')).toBeUndefined()
  expect(w.notices).toContain('⏳ Usage limit lifted — back to normal')
})

test('an in-process /resume drops the old conversation\'s limit resume (R2-16)', async ($, on) => {
  const w = world(on, { now: 1_000_000 })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure([{ kind: 'seven_day', percentUsed: 96, resetsAt: iso(1_000_000 + 3 * HOUR) }]))
  await w.clock.settle()
  w.sessionId.value = 's2'
  await $.classic.SessionStart({ source: 'resume' } as never)
  await w.clock.advance(3 * HOUR + 600_000)
  expect(w.submits.some(s => s.text.includes('limit has reset'))).toBe(false)
  expect([...w.files.entries()].filter(([k]) => k.includes('/events/')).map(([, v]) => v).join('')).toContain('resume-dropped')
})

test('an early stop with a fresh /vho handover already on disk writes no second one and leaves its clear waiting (R2-12)', async ($, on) => {
  const w = world(on, { now: 1_000_000 })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.command.run({ command: 'vho', args: '', origin: { kind: 'composer' } as never } as never)
  await w.clock.settle()
  expect(asks(w)).toBe(1)
  w.draft.value = 'half a thought'
  await $.tool.call(write)
  await w.clock.settle()
  expect(w.notices.some(n => n.includes('there is a draft'))).toBe(true)
  await $.session.measure(measure([{ kind: 'seven_day', percentUsed: 96, resetsAt: iso(1_000_000 + HOUR) }]))
  await w.clock.settle()
  expect(asks(w)).toBe(1)                                             // no second handover
  expect(w.state.get('context-vigil-mod.pending')).not.toBe(null)    // the requested one is untouched
  w.draft.value = ''
  await w.clock.advance(5000)
  expect(w.commands).toContain('clear')                               // the person's clear still happens
  await w.clock.advance(HOUR + 300_000)
  expect(w.submits.find(s => s.text.includes('limit has reset'))?.text).toContain('/handovers/s1-1.md')
})

test('a skipped limit resume keeps its handover; a later manual /clear injects it and says there is no automatic resume (R2-17)', async ($, on) => {
  const w = world(on, { now: 1_000_000 })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure([{ kind: 'seven_day', percentUsed: 96, resetsAt: iso(1_000_000 + HOUR) }]))
  await w.clock.settle()
  await $.tool.call(write)
  await w.clock.advance(1000)
  await $.prompt.submit(human('back already'))
  await w.clock.advance(HOUR + 300_000)
  expect(w.notices.some(n => n.includes('you are back') && n.includes('s1-1.md'))).toBe(true)
  expect(w.state.get('context-vigil-mod.pending')).not.toBe(null)    // still /clear-able, as the notice says
  const before = w.submits.length
  w.sessionId.value = 's2'
  const ss = await $.classic.SessionStart({ source: 'clear' } as never)
  await w.clock.advance(1000)
  expect(ss.additionalContext?.join('\n')).toContain('## Goal')
  expect(w.notices.some(n => n.includes('Handover injected') && n.includes('no automatic resume') && n.includes('s1-1.md'))).toBe(true)
  expect(w.submits.length).toBe(before)                               // nothing sent over the new session
})

test('limit events log which window they are about, not just the event kind (R2-13)', async ($, on) => {
  const w = world(on, { now: 1_000_000 })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure([{ kind: 'seven_day', percentUsed: 100, resetsAt: iso(1_000_000 + HOUR) }]))
  await w.clock.settle()
  const lines = [...w.files.entries()].find(([k]) => k.includes('/events/'))?.[1].trim().split('\n').map(l => JSON.parse(l)) ?? []
  expect(lines.find(l => l.kind === 'limit.early_stop')?.window).toBe('seven_day')
  expect(lines.find(l => l.kind === 'limit.latched')?.window).toBe('seven_day')
})
