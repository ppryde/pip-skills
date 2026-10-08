import { expect, test } from 'claude-code/testing'
import { START, human, turn, usageTurn, world, type World } from './world'
import { V } from '../../plugins/context-vigil-mod/core/voice'

const MIN = 60_000
const TOOL = 'mcp__context-vigil-mod__vigil_handover'
const measure = (percent: number) => ({ context: { window: 1_000_000, percent }, rateLimits: [], changed: ['context'] as never })
const write = { tool: TOOL, tool_use_id: 'h', goal: 'G', state: 'S', next_step: 'N', session_name: 'Name' } as never
const LL = { store: { settings: { lastLight: true, nudgeAt: 90 } } }
const asks = (w: { submits: { text: string }[] }) => w.submits.filter(s => s.text.includes(TOOL)).length
const PENDING = 'context-vigil-mod.pending'
const eventLog = (w: World) => [...w.files.entries()].find(([k]) => k.includes('/events/'))?.[1] ?? ''
const count = (text: string, needle: string) => text.split(needle).length - 1

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

// Fire time is the only time the cache lifetime is checked (PROBES §11).
async function idleUntilTimer($: any, w: World, minutes = 55) {
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())
  await w.clock.advance(minutes * MIN)
}

test('the cache lifetime is read once, at fire time, from a bounded tail; never per turn', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())
  await $.prompt.submit(human('more'))
  await $.turn.complete(turn('2'))
  await w.clock.settle()
  expect(w.tails.length).toBe(0)
  await w.clock.advance(55 * MIN)
  expect(w.tails.length).toBe(1)
  expect(w.tails[0]?.[2]).toContain('tail -c 65536')
  expect(asks(w)).toBe(1)
})

test('a latest 1-hour write fires', async ($, on) => {
  const w = world(on, LL)
  await idleUntilTimer($, w)
  expect(asks(w)).toBe(1)
  expect(eventLog(w)).not.toContain('last_light.skip')
})

test('a latest 5-minute write does not fire, and says why', async ($, on) => {
  const w = world(on, LL)
  w.cacheWrites.value = { h1: 0, m5: 100 }
  await idleUntilTimer($, w)
  expect(asks(w)).toBe(0)
  expect(eventLog(w)).toContain('last_light.skip')
  expect(eventLog(w)).toContain('"reason":"ttl-5m"')
})

test('mixed 1h and 5m tokens count as 5m', async ($, on) => {
  const w = world(on, LL)
  w.cacheWrites.value = { h1: 900, m5: 1 }
  await idleUntilTimer($, w)
  expect(asks(w)).toBe(0)
  expect(eventLog(w)).toContain('"reason":"ttl-5m"')
})

for (const value of ['none', 'fail'] as const) {
  test(`${value === 'none' ? 'nothing found in the tail' : 'an unreadable transcript'} does not fire; no widening, no retry`, async ($, on) => {
    const w = world(on, LL)
    w.cacheWrites.value = value
    await idleUntilTimer($, w)
    expect(asks(w)).toBe(0)
    expect(eventLog(w)).toContain('"reason":"ttl-unknown"')
    await w.clock.advance(120 * MIN)
    expect(w.tails.length).toBe(1)
    expect(asks(w)).toBe(0)
  })
}

test('walks back over pure cache reads to the latest write', async ($, on) => {
  const w = world(on, LL)
  w.cacheWrites.value = { raw: '"cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":40}\n"cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":0}\n"cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":0}\n' }
  await idleUntilTimer($, w)
  expect(asks(w)).toBe(1)
})

test('a fire that other conditions block does not touch the transcript', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(10))     // below the threshold
  await $.turn.complete(turn())
  await w.clock.advance(55 * MIN)
  expect(w.tails.length).toBe(0)
})

test('the transcript is read from the path the session reported', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.classic.SessionStart({ source: 'startup', transcript_path: '/t/s1.jsonl' } as never)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())
  await w.clock.advance(55 * MIN)
  expect(w.tails.at(-1)?.at(-1)).toBe('/t/s1.jsonl')
})

test('without a reported path the transcript is found by the project folder convention', async ($, on) => {
  const w = world(on, LL)
  await idleUntilTimer($, w)
  expect(w.tails.at(-1)?.at(-1)).toBe('/cfg/projects/-repo/s1.jsonl')
})

// R1-07 (hot-reload half, deferred): a reload counts as you being here (arming safety), so it
// fails closed for that idle period; the next turn schedules last light normally again.
test('a hot reload skips that idle period\'s last light; the next turn re-arms it', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())
  await w.clock.advance(10 * MIN)
  await $.session.start(START)          // the reload cancels the scheduled fire
  await w.clock.advance(45 * MIN)
  expect(asks(w)).toBe(0)
  await $.turn.complete(turn('next'))
  await w.clock.advance(55 * MIN)
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

// Information layer (PROBES §11): what the session's cache is, shown; never a gate.
const TTL = 'context-vigil-mod.cacheTtl'
const BAND = { plugin: 'context-vigil-mod', surface: 'terminal' as const, component: 'AbovePrompt' as const, props: { hasSurvey: false, isWorking: false } as never }
const INFO = { type: 'Text' as const, text: /Last light is off for this session/ }
async function infoShown($: any) {
  const ui = await $.ui.mount(BAND)
  const found = (await ui.find(INFO)) !== undefined
  await ui.unmount()
  return found
}
async function first5m($: any, w: World) {
  w.cacheWrites.value = { h1: 0, m5: 100 }
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.turn.complete(usageTurn(5))
  await w.clock.settle()
}

test('the first turn that wrote to the cache reads the type once; later turns never read again', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.turn.complete(usageTurn(5))
  await w.clock.settle()
  expect(w.tails.length).toBe(1)
  expect(w.state.get(TTL)).toBe('1h')
  await $.turn.complete(usageTurn(5, '2'))
  await $.turn.complete(usageTurn(0, '3'))
  await w.clock.settle()
  expect(w.tails.length).toBe(1)
})

test('a turn with no cache write, or a subagent turn, does not read', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.turn.complete(usageTurn(0))
  await $.turn.complete({ ...usageTurn(5), agentId: 'sub' } as never)
  await $.turn.complete(turn())
  await w.clock.settle()
  expect(w.tails.length).toBe(0)
})

test('an unreadable transcript is unknown and is not retried every turn', async ($, on) => {
  const w = world(on, LL)
  w.cacheWrites.value = 'fail'
  await $.session.start(START)
  await $.turn.complete(usageTurn(5))
  await w.clock.settle()
  await $.turn.complete(usageTurn(5, '2'))
  await w.clock.settle()
  expect(w.tails.length).toBe(1)
  expect(w.state.get(TTL) ?? 'unknown').toBe('unknown')
  expect(await infoShown($)).toBe(false)
})

test('5-minute cache with last light on: the info line shows, and the log says so once', async ($, on) => {
  const w = world(on, LL)
  await first5m($, w)
  expect(w.state.get(TTL)).toBe('5m')
  expect(await infoShown($)).toBe(true)
  expect(count(eventLog(w), '"kind":"last_light.off"')).toBe(1)
  expect(eventLog(w)).toContain('"source":"response"')
})

test('last light off: nothing is shown or logged for a 5-minute cache', async ($, on) => {
  const w = world(on, { store: { settings: { lastLight: false, nudgeAt: 90 } } })
  await first5m($, w)
  expect(await infoShown($)).toBe(false)
  expect(eventLog(w)).not.toContain('last_light.off')
})

test('a 1-hour cache shows nothing', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.turn.complete(usageTurn(5))
  await w.clock.settle()
  expect(await infoShown($)).toBe(false)
})

test('R1-20: the info line is Text only — no Button, no hotkey, so a leading 0 stays the person\'s', async ($, on) => {
  const w = world(on, LL)
  await first5m($, w)
  const ui = await $.ui.mount(BAND)
  expect(await ui.find(INFO)).toBeDefined()
  expect(await ui.find({ type: 'Button' as const })).toBeUndefined()
  await ui.unmount()
})

test('R1-20: the next human prompt hides the line; a plugin prompt does not; a later 5m switch shows it again', async ($, on) => {
  const w = world(on, LL)
  await first5m($, w)
  await $.prompt.submit({ text: 'resume', wait: false, origin: { kind: 'plugin' } as never })
  expect(await infoShown($)).toBe(true)
  await $.prompt.submit(human('hello'))
  expect(await infoShown($)).toBe(false)
  await $.classic.PostModelSwitch({ cache_ttl: '1h' } as never)
  await $.classic.PostModelSwitch({ cache_ttl: '5m' } as never)
  expect(await infoShown($)).toBe(true)
})

test('the threshold bar wins while both apply; the info line returns after it', async ($, on) => {
  const w = world(on, LL)
  await first5m($, w)
  await $.session.measure(measure(95))
  let ui = await $.ui.mount(BAND)
  expect(await ui.find({ key: 'handover' })).toBeDefined()
  expect(await ui.find(INFO)).toBeUndefined()
  await ui.press({ key: 'later' })
  await ui.unmount()
  expect(await infoShown($)).toBe(true)
})

test('a switch to a 1-hour cache hides the line and says last light is back on', async ($, on) => {
  const w = world(on, LL)
  await first5m($, w)
  await $.classic.PostModelSwitch({ cache_ttl: '1h' } as never)
  expect(w.state.get(TTL)).toBe('1h')
  expect(await infoShown($)).toBe(false)
  expect(w.notices).toContain('🌅 Last light is back on — 1-hour prompt cache')
  expect(eventLog(w)).toContain('"kind":"last_light.on"')
})

test('a switch to a 5-minute cache shows the line; no notice for 1h learnt from unknown', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.classic.PostModelSwitch({ cache_ttl: '1h' } as never)
  expect(w.notices.some(n => n.includes('back on'))).toBe(false)
  await $.classic.PostModelSwitch({ cache_ttl: '5m' } as never)
  expect(await infoShown($)).toBe(true)
  expect(eventLog(w)).toContain('"source":"switch"')
})

test('PreModelSwitch is ignored', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.classic.PreModelSwitch({ cache_ttl: '5m' } as never)
  expect(w.state.get(TTL) ?? 'unknown').toBe('unknown')
})

test('a /clear resets the type to unknown and reads again on the new session', async ($, on) => {
  const w = world(on, LL)
  await first5m($, w)
  await $.classic.SessionStart({ source: 'clear' } as never)
  expect(w.state.get(TTL) ?? 'unknown').toBe('unknown')
  expect(await infoShown($)).toBe(false)
  w.cacheWrites.value = { h1: 10, m5: 0 }
  await $.turn.complete(usageTurn(5, '9'))
  await w.clock.settle()
  expect(w.tails.length).toBe(2)
  expect(w.state.get(TTL)).toBe('1h')
})

test('fire-time check stays the only gate: a 1h state does not override a 5m transcript', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(usageTurn(5))
  await w.clock.settle()
  w.cacheWrites.value = { h1: 0, m5: 9 }
  await w.clock.advance(55 * MIN)
  expect(asks(w)).toBe(0)
})

// R1-05: coming back before the cache expired drops the last-light handover.
test('R1-05: a return before the cache expires drops the pending, and a later last light can fire', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())
  await w.clock.advance(55 * MIN)
  await $.tool.call(write)
  await w.clock.settle()
  expect(w.state.get(PENDING)).toBeTruthy()
  await w.clock.advance(3 * MIN)                      // 58 min: the cache is still warm
  await $.prompt.submit(human('back'))
  expect(w.state.get(PENDING)).toBeNull()
  expect(w.store.get('pending:s1')).toBeUndefined()
  expect(eventLog(w)).toContain('last_light.dropped')
  await $.turn.complete(turn('after'))
  await w.clock.advance(55 * MIN)
  expect(asks(w)).toBe(2)
})

test('R1-05: a return after the cache expired keeps the pending for the ask', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())
  await w.clock.advance(55 * MIN)
  await $.tool.call(write)
  await w.clock.settle()
  await w.clock.advance(65 * MIN)
  await $.prompt.submit(human('back'))
  expect(w.state.get(PENDING)).toBeTruthy()
  expect(eventLog(w)).not.toContain('last_light.dropped')
})

// R1-07: "you idle" for last light is: nothing from you since the agent's last turn.
test('R1-07: with a 60-minute idle window last light still fires at +55', async ($, on) => {
  const w = world(on, { store: { settings: { lastLight: true, nudgeAt: 90, idleMin: 60 } } })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())
  await w.clock.advance(55 * MIN)
  expect(asks(w)).toBe(1)
})

test('R1-07: a draft after the turn blocks that period\'s last light', async ($, on) => {
  const w = world(on, { store: { settings: { lastLight: true, nudgeAt: 90, idleMin: 60 } } })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())
  await w.clock.advance(40 * MIN)
  w.draft.value = 'typing'               // a draft in the box is you being here
  await w.clock.advance(15 * MIN)
  expect(asks(w)).toBe(0)
})

test('R1-14: a subagent turn neither moves the cache clock nor re-arms the last-light timer', async ($, on) => {
  const w = world(on, LL)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())
  await w.clock.advance(30 * MIN)
  await $.turn.complete({ ...turn('sub'), agentId: 'a1' } as never)
  await w.clock.advance(25 * MIN)   // T+55: the main cache's own clock
  expect(asks(w)).toBe(1)
  expect(w.state.get('context-vigil-mod.lastApiAt')).toBe(1_000_000)
})

test('R1-19: a second prompt while the return question is open joins the first; nothing is lost', async ($, on) => {
  const w = world(on, LL)
  await heldReturn($, w, 'Resume from handover')
  const a = await $.prompt.submit(human('one'))
  const b = await $.prompt.submit(human('two'))
  expect((a as { drop?: string }).drop).toBeDefined()
  expect((b as { drop?: string }).drop).toBeDefined()
  await w.clock.settle()
  expect(w.state.get(PENDING)).not.toBe(null)   // the Resume answer was not undone by a second ask
  w.sessionId.value = 's2'
  await $.classic.SessionStart({ source: 'clear' } as never)
  await w.clock.advance(500)
  const sent = w.submits.at(-1)?.text ?? ''
  expect(sent).toContain('one')
  expect(sent).toContain('two')
})

const HOUR = 60 * MIN
const storedLastLight = (now: number, ageMs: number) => ({
  session: 's1', path: '/cfg/context-vigil-mod/handovers/s1-1.md', name: 'Name', reason: 'last_light', markdown: '## Goal\nG', resume: false, followUp: null, createdAt: now - ageMs,
})

test('after a restart the first prompt is held and offered a choice, however long the gap (R2-05)', async ($, on) => {
  const now = 20 * HOUR
  const w = world(on, { ...LL, now, store: { ...LL.store, 'pending:s1': storedLastLight(now, 8 * HOUR) } })
  await $.session.start(START)                      // a fresh process: lastApiAt is unknown
  w.askAnswer.value = 'Carry on'
  const r = await $.prompt.submit(human('morning'))
  expect((r as { drop?: string }).drop).toBe(V.heldForLastLight)
  await w.clock.settle()
  expect(w.submits.at(-1)?.text).toBe('morning')
  expect(eventLog(w)).toContain('last_light.choice')
})

test('after a restart a last-light handover from ten minutes ago is dropped, not held (R2-05, R1-05 kept)', async ($, on) => {
  const now = 20 * HOUR
  const w = world(on, { ...LL, now, store: { ...LL.store, 'pending:s1': storedLastLight(now, 10 * MIN) } })
  await $.session.start(START)
  const r = await $.prompt.submit(human('back already'))
  expect((r as { drop?: string }).drop).toBeUndefined()
  expect(eventLog(w)).toContain('last_light.dropped')
})

test('an in-process /resume holds the first prompt for a stored last-light handover too (R2-05)', async ($, on) => {
  const now = 20 * HOUR
  const w = world(on, { ...LL, now, store: { ...LL.store, 'pending:s2': storedLastLight(now, 8 * HOUR) } })
  await $.session.start(START)
  w.sessionId.value = 's2'
  await $.classic.SessionStart({ source: 'resume' } as never)
  w.askAnswer.value = 'Carry on'
  const r = await $.prompt.submit(human('morning'))
  expect((r as { drop?: string }).drop).toBe(V.heldForLastLight)
})

// R2-11: the held messages live in $.state, so a reload while the ask is open loses nothing.
test('a reload while the ask is open re-opens it; whichever answer acts first sends the held text once (R2-11)', async ($, on) => {
  const w = world(on, LL)
  await heldReturn($, w, 'Carry on')
  w.askHold.held = true
  const r = await $.prompt.submit(human('one'))
  expect((r as { drop?: string }).drop).toBe(V.heldForLastLight)
  await w.clock.advance(1)
  expect(w.askHold.waiting.length).toBe(1)
  await $.session.start(START)                        // the reload: module variables are gone, $.state is not
  await w.clock.advance(1)
  expect(w.askHold.waiting.length).toBe(2)            // the new module asks again, it does not forget
  w.askHold.waiting[1]?.('Carry on')
  await w.clock.settle()
  w.askHold.waiting[0]?.('Carry on')                  // the old dialog answers late: inert
  await w.clock.settle()
  expect(w.submits.filter(s => s.text === 'one').length).toBe(1)
})

test('a /clear while the return question is open still sends the held text after the injected handover (R3-02)', async ($, on) => {
  const w = world(on, LL)
  await heldReturn($, w, 'Carry on')
  w.askHold.held = true
  await $.prompt.submit(human('one'))
  await w.clock.advance(1)
  expect(w.askHold.waiting.length).toBe(1)
  w.sessionId.value = 's2'
  const ss = await $.classic.SessionStart({ source: 'clear' } as never)
  expect(ss.additionalContext?.join('\n')).toContain('## Goal')
  await w.clock.advance(500)
  expect(w.submits.filter(s => s.text === 'one').length).toBe(1)
  w.askHold.waiting[0]?.('Carry on')                  // the dialog outlives the clear: inert, nothing twice
  await w.clock.settle()
  expect(w.submits.filter(s => s.text === 'one').length).toBe(1)
})

test('a second held message while a Resume is already queued rides the clear with the first (R3-02)', async ($, on) => {
  const w = world(on, LL)
  await heldReturn($, w, 'Resume from handover')
  w.clearHold.held = true
  await $.prompt.submit(human('one'))
  await w.clock.settle()
  expect(w.commands).toContain('clear')
  w.askHold.held = true
  await $.prompt.submit(human('two'))
  await w.clock.advance(1)
  w.clearHold.release()
  await w.clock.settle()
  w.sessionId.value = 's2'
  await $.classic.SessionStart({ source: 'clear' } as never)
  await w.clock.advance(500)
  const sent = w.submits.at(-1)?.text ?? ''
  expect(sent).toContain('one')
  expect(sent).toContain('two')
})

test('a /resume while the return question is open never submits the held text into the other conversation; a notice carries it (R3-02)', async ($, on) => {
  const w = world(on, LL)
  await heldReturn($, w, 'Carry on')
  w.askHold.held = true
  await $.prompt.submit(human('one'))
  await w.clock.advance(1)
  w.sessionId.value = 's9'
  await $.classic.SessionStart({ source: 'resume' } as never)
  await w.clock.settle()
  expect(w.notices.some(n => n.includes('held message was not sent') && n.includes('one'))).toBe(true)
  w.askHold.waiting[0]?.('Carry on')
  await w.clock.settle()
  expect(w.submits.filter(s => s.text === 'one').length).toBe(0)
})

test('an answer typed under Other is carry-on with the typed text appended, never a clear (R2-11)', async ($, on) => {
  const w = world(on, LL)
  await heldReturn($, w, 'use the handover please')
  await $.prompt.submit(human('morning'))
  await w.clock.settle()
  const sent = w.submits.at(-1)?.text ?? ''
  expect(sent).toContain('morning')
  expect(sent).toContain('use the handover please')
  expect(w.commands).not.toContain('clear')
})

test('under stand-down last light logs a skip, never "fired", and spends no arm (R2-14)', async ($, on) => {
  const classic = { '/cfg/settings.json': JSON.stringify({ hooks: { Stop: [{ hooks: [{ type: 'command', command: '"/s/context-vigil/scripts/context-vigil" hook stop' }] }] } }) }
  const w = world(on, { ...LL, files: classic })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())
  await w.clock.advance(55 * MIN)
  expect(asks(w)).toBe(0)
  expect(eventLog(w)).not.toContain('last_light.fired')
  expect(eventLog(w)).toContain('"reason":"standdown"')
})
