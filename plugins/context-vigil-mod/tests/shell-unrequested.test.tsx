import { expect, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import { V } from '../plugin/core/voice'
import { START, human, turn, world, type World, endInto } from './world'

const MIN = 60_000
const TOOL = 'mcp__context-vigil-mod__vigil_handover'
const call = (id = 'h1') => ({ tool: TOOL, tool_use_id: id, goal: 'G', state: 'S', next_step: 'N', session_name: 'Name' })
const measure = (percent: number) => ({ context: { window: 1_000_000, percent }, rateLimits: [], changed: ['context'] as never })
const BAND = () => ({ plugin: 'context-vigil-mod', surface: 'terminal' as const, component: 'AbovePrompt' as const, props: { hasSurvey: false, isWorking: false } as never })
const cmd = (command: string) => ({ command, args: '', origin: { kind: 'composer' } as never }) as never
const FILE = (n: number) => `/cfg/context-vigil-mod/handovers/s1-${n}.md`
const ASK = V.unrequestedAsk(FILE(1))
const PHONE_HANDOVER = '📜 Hand over now'

const clears = (w: World) => w.commands.filter(c => c === 'clear').length
const unasked = (w: World) => w.notices.filter(n => n.includes('it was not asked for')).length

// The instruction's own turn runs and ends with no tool call, twice: the mod gives up on it (R1-02).
async function instructionFails($: Engine, w: World) {
  for (const id of ['i1', 'i2']) {
    await $.turn.start({ text: w.submits.at(-1)?.text ?? '', turnId: id } as never)
    await $.turn.complete(turn(id))
    await w.clock.settle()
  }
  expect(w.notices).toContain(V.handoverFailed)
}

async function clearsAndResumesFrom($: Engine, w: World, file: string) {
  expect(clears(w)).toBe(1)
  w.sessionId.value = 's2'
  await endInto($, w, 'clear')
  await w.clock.advance(500)
  expect(w.submits.at(-1)?.text).toContain(`(saved at ${file})`)
}

// Root cause: the person's request was the one-shot `awaiting` slot. Once an earlier save spent it,
// a second save from the same request (its clear still waiting) read as volunteered: "not asked
// for, so nothing was cleared", and the clear used the older file. Every explicit control now records consent.
const starts: [string, ($: Engine, w: World) => Promise<void>][] = [
  ['the bar\'s Hand over now', async ($, w) => {
    await $.session.measure(measure(36))
    const ui = await $.ui.mount(BAND())
    await ui.press({ key: 'handover' })
    await ui.unmount()
    await w.clock.settle()
  }],
  ['the phone dialog\'s Hand over now', async ($, w) => {
    w.askAnswer.value = PHONE_HANDOVER
    await $.prompt.submit(human('hi', 'bridge'))
    await $.session.measure(measure(36))
    await w.clock.settle()
    w.askAnswer.value = null
  }],
  ['/vho', async ($, w) => { await $.command.run(cmd('vho')); await w.clock.settle() }],
  ['/vigil-handover', async ($, w) => { await $.command.run(cmd('vigil-handover')); await w.clock.settle() }],
  ['plain words', async ($, w) => { await $.prompt.submit(human('do a handover')); await w.clock.settle() }],
]

for (const [name, start] of starts) {
  test(`${name}: a second save while its clear waits is still asked for, and the newer one is used`, async ($, on) => {
    const w = world(on)
    await $.session.start(START)
    await $.prompt.submit(human('hi'))
    await start($, w)
    expect(w.submits.at(-1)?.text).toContain(TOOL)
    w.draft.value = 'half a sen'
    await $.tool.call(call() as never)
    await w.clock.settle()
    await $.tool.call(call('h2') as never)
    await w.clock.settle()
    expect(unasked(w)).toBe(0)
    expect(w.asks.map(q => q.question)).not.toContain(V.unrequestedAsk(FILE(2)))
    w.draft.value = ''
    await w.clock.advance(2000)
    await clearsAndResumesFrom($, w, FILE(2))
  })
}

test('told the handover failed (no tool call, twice): the request is over, a later save gets the dialog', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.command.run(cmd('vho'))
  await w.clock.settle()
  await instructionFails($, w)
  expect(w.state.get('context-vigil-mod.consent')).toBeNull()
  await $.prompt.submit(human('go on then'))
  await $.tool.call(call() as never)
  await w.clock.settle()
  expect(clears(w)).toBe(0)
  expect(w.asks.map(q => q.question)).toEqual([ASK])
})

test('the request ends when its clear is issued: a save after it is the repeat line, no dialog', async ($, on) => {
  const w = world(on)
  w.clearHold.held = true
  await $.session.start(START)
  await $.command.run(cmd('vho'))
  await w.clock.settle()
  await $.tool.call(call() as never)
  await w.clock.settle()
  await $.tool.call(call('h2') as never)
  await w.clock.settle()
  expect(w.notices).toContain(V.handoverRepeat(FILE(2)))
  expect(w.asks).toHaveLength(0)
  expect(w.state.get('context-vigil-mod.consent')).toBeNull()
})

test('Esc on the instruction turn takes the request back: a later save is volunteered', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run(cmd('vho'))
  await w.clock.settle()
  await $.turn.start({ text: w.submits.at(-1)?.text ?? '', turnId: 'i1' } as never)
  await $.turn.complete({ ...turn('i1'), isAborted: true, reason: 'aborted' } as never)
  await w.clock.settle()
  await $.tool.call(call() as never)
  await w.clock.settle()
  expect(clears(w)).toBe(0)
  expect(w.asks.map(q => q.question)).toEqual([ASK])
})

test('told the handover failed (the instruction submit refused): the request is over, a later save gets the dialog', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  w.submitRefused.value = true
  await $.command.run(cmd('vho'))
  await w.clock.settle()
  expect(w.notices).toContain(V.handoverFailed)
  expect(w.state.get('context-vigil-mod.consent')).toBeNull()
  w.submitRefused.value = false
  await $.tool.call(call() as never)
  await w.clock.settle()
  expect(clears(w)).toBe(0)
  expect(w.asks.map(q => q.question)).toEqual([ASK])
})

// 31 simulated minutes of the draft guard's 2 s recheck (~930 rounds): ~4.5 s of real work, marginal at the 5 s default.
test('the request lapses after 30 minutes with no clear', { timeoutMs: 15_000 }, async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run(cmd('vho'))
  await w.clock.settle()
  w.draft.value = 'half a sen'                     // the clear waits on the draft
  await $.tool.call(call() as never)
  await w.clock.settle()
  await w.clock.advance(31 * MIN)
  await $.tool.call(call('h2') as never)
  await w.clock.settle()
  expect(clears(w)).toBe(0)
  expect(w.asks.map(q => q.question).filter(q => q !== V.draftTitle)).toEqual([V.unrequestedAsk(FILE(2))])
})

// A handover the model saved on its own: a dialog, phone and terminal alike.
async function volunteer($: Engine, w: World, answer: string | null) {
  w.askAnswer.value = answer
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  const r = await $.tool.call(call() as never)
  expect(String((r as { result?: unknown }).result)).toContain('nothing was cleared')
  await w.clock.settle()
}

test('an unrequested save asks what to do with it: three choices, headed, the file named', async ($, on) => {
  const w = world(on)
  await volunteer($, w, null)
  expect(w.asks).toEqual([{ question: ASK, header: V.unrequestedHeader, multiSelect: false, options: [V.unrequestedUpdate, V.unrequestedClear, V.unrequestedLeave], descriptions: ['', '', ''] }])
  expect(V.unrequestedHeader.length).toBeLessThanOrEqual(12)
  expect(ASK.endsWith('?')).toBe(true)
})

test('Clear now: clears and resumes from the saved handover', async ($, on) => {
  const w = world(on)
  await volunteer($, w, V.unrequestedClear)
  await clearsAndResumesFrom($, w, FILE(1))
})

test('Update it, then clear: a fresh instruction, and its save clears and resumes from the new file', async ($, on) => {
  const w = world(on)
  await volunteer($, w, V.unrequestedUpdate)
  expect(clears(w)).toBe(0)
  expect(w.submits.at(-1)?.text).toContain('The person asked for a handover')
  await $.tool.call(call('h2') as never)
  await w.clock.settle()
  await clearsAndResumesFrom($, w, FILE(2))
})

for (const [name, answer] of [['Leave it', V.unrequestedLeave], ['a dismissed dialog', null], ['free text', 'not now']] as const) {
  test(`${name}: today's notice, nothing cleared, and /vho still clears into it`, async ($, on) => {
    const w = world(on)
    await volunteer($, w, answer)
    expect(clears(w)).toBe(0)
    expect(w.notices).toContain(V.handoverUnrequested(FILE(1)))
    await $.command.run(cmd('vho'))
    await w.clock.settle()
    expect(clears(w)).toBe(1)
  })
}

test('the dialog never holds up the tool call or the session', async ($, on) => {
  const w = world(on)
  w.askHold.held = true
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  const r = await $.tool.call(call() as never)
  expect(String((r as { result?: unknown }).result)).toContain('Saved handover')
  await w.clock.settle()
  expect(w.askHold.waiting).toHaveLength(1)
  await $.prompt.submit(human('carry on'))
  w.askHold.waiting[0]?.(V.unrequestedClear)
  await w.clock.settle()
  expect(clears(w)).toBe(1)
})

test('one dialog at a time: a later save while it is open moves it on to the newer file', async ($, on) => {
  const w = world(on)
  w.askHold.held = true
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.tool.call(call() as never)
  await w.clock.settle()
  await $.tool.call(call('h2') as never)
  await w.clock.settle()
  expect(w.askHold.waiting).toHaveLength(1)
  w.askHold.waiting[0]?.(V.unrequestedClear)
  await w.clock.settle()
  await clearsAndResumesFrom($, w, FILE(2))
})

test('an answer about a handover that is gone (a clear in between) changes nothing', async ($, on) => {
  const w = world(on)
  w.askHold.held = true
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.tool.call(call() as never)
  await w.clock.settle()
  w.sessionId.value = 's2'
  await endInto($, w, 'clear')
  await $.tool.call(call('h2') as never)           // the new session's own volunteer, with the old dialog still open
  await w.clock.settle()
  expect(w.notices).toContain(V.handoverUnrequested('/cfg/context-vigil-mod/handovers/s2-1.md'))
  w.askHold.waiting[0]?.(V.unrequestedClear)
  await w.clock.settle()
  expect(w.notices).toContain(V.unrequestedGone)
  expect(clears(w)).toBe(0)
})

test('under the limit latch: no dialog, the notice only', async ($, on) => {
  const w = world(on, { store: { latch: { kind: 'seven_day', resetsAtMs: 1_000_000 + 60 * MIN } } })
  await volunteer($, w, V.unrequestedClear)
  expect(w.asks).toHaveLength(0)
  expect(w.notices).toContain(V.handoverUnrequested(FILE(1)))
  expect(clears(w)).toBe(0)
})

test('after an early stop: no dialog, so a clear never spends what the stop saved', async ($, on) => {
  const w = world(on, { store: { settings: { limits: true, limitPct: 95 } } })
  w.askAnswer.value = V.unrequestedClear
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure({ context: { window: 1_000_000, percent: 10 }, rateLimits: [{ kind: 'seven_day', percentUsed: 96, resetsAt: new Date(1_000_000 + 60 * MIN).toISOString() }], changed: ['rateLimits'] } as never)
  await w.clock.settle()
  await $.tool.call(call() as never)               // the limit handover
  await w.clock.settle()
  await $.tool.call(call('h2') as never)           // the model writes another
  await w.clock.settle()
  expect(w.asks).toHaveLength(0)
  expect(w.notices).toContain(V.handoverUnrequested(FILE(2)))
  expect(clears(w)).toBe(0)
})

test('classic installed: the mod stands down, the notice only', async ($, on) => {
  const w = world(on, { files: { '/cfg/settings.json': JSON.stringify({ hooks: { Stop: [{ hooks: [{ type: 'command', command: '"/s/context-vigil/scripts/context-vigil" hook stop' }] }] } }) } })
  await volunteer($, w, V.unrequestedClear)
  expect(w.asks).toHaveLength(0)
  expect(clears(w)).toBe(0)
})

test('a hot reload with a volunteered handover pending offers it, never clears it', async ($, on) => {
  const w = world(on)
  await volunteer($, w, V.unrequestedLeave)
  await $.session.start(START)                     // the reload: $.state kept
  await w.clock.settle()
  expect(clears(w)).toBe(0)
  expect(w.notices).toContain(V.pendingOffer(FILE(1)))
})
