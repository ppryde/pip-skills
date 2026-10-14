import { expect, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import { START, human, turn, world } from './world'
import { V } from '../plugin/core/voice'

const MIN = 60_000
const TOOL = 'mcp__context-vigil-mod__vigil_handover'
const BAND = () => ({ plugin: 'context-vigil-mod', surface: 'terminal' as const, component: 'AbovePrompt' as const, props: { hasSurvey: false, isWorking: false } as never })
const measure = (percent: number) => ({ context: { window: 1_000_000, percent }, rateLimits: [], changed: ['context'] as never })
const cmd = (command: string) => ({ command, args: '', origin: { kind: 'composer' } as never }) as never
const text = (r: unknown) => String((r as { text?: unknown }).text ?? '')
const asks = (w: { submits: { text: string }[] }) => w.submits.filter(s => s.text.includes(TOOL)).length
const call = { tool: TOOL, tool_use_id: 'h1', goal: 'G', state: 'S', next_step: 'N', session_name: 'Name' } as never

async function barShown($: Engine) {
  const ui = await $.ui.mount(BAND())
  const found = (await ui.find({ key: 'handover' })) !== undefined
  await ui.unmount()
  return found
}
async function pausedLine($: Engine) {
  const ui = await $.ui.mount(BAND())
  const found = (await ui.find({ type: 'Text', text: /vigil paused/ })) !== undefined
  await ui.unmount()
  return found
}

test('paused: no bar at the threshold; the line shows; the toast says how to turn it back on', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  expect(text(await $.command.run(cmd('vigil-pause')))).toBe(V.paused)
  expect(w.notices).toContain(V.paused)
  await $.session.measure(measure(41))
  expect(await barShown($)).toBe(false)
  expect(await pausedLine($)).toBe(true)
  expect(w.state.get('context-vigil-mod.lastNudged') ?? null).toBeNull()   // not spent
  expect(text(await $.command.run(cmd('vigil-pause')))).toBe(V.paused)       // idempotent
})

test('paused: an auto-mode session does not start a threshold handover', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await $.session.start(START)
  await $.prompt.submit(human('go'))
  await $.command.run(cmd('vigil-pause'))
  await w.clock.advance(31 * MIN)
  await $.tool.call({ tool: 'Bash', tool_use_id: 'b', command: 'ls' } as never)
  await $.session.measure(measure(20))
  await $.session.measure(measure(36))
  await w.clock.settle()
  expect(asks(w)).toBe(0)
  expect([...w.files.values()].join('')).toContain('paused.skip')
})

test('a pause survives a /clear', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run(cmd('vigil-pause'))
  w.sessionId.value = 's2'
  await $.classic.SessionStart({ source: 'clear' } as never)
  await $.session.measure(measure(41))
  expect(await barShown($)).toBe(false)
  expect(await pausedLine($)).toBe(true)
})

test('paused: /vho still hands over', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run(cmd('vigil-pause'))
  await $.command.run(cmd('vho'))
  await w.clock.settle()
  expect(asks(w)).toBe(1)
})

test('paused: last light still fires', async ($, on) => {
  const w = world(on, { store: { settings: { lastLight: true, nudgeAt: 90 } } })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.command.run(cmd('vigil-pause'))
  await $.session.measure(measure(30))
  await $.turn.complete(turn())
  await w.clock.advance(55 * MIN)
  expect(asks(w)).toBe(1)
  expect(w.submits.at(-1)?.text).toContain('Do not clear')
})

test('resume after a dismiss brings the bar back at the current %', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.session.measure(measure(41))
  let ui = await $.ui.mount(BAND())
  await ui.press({ key: 'dismiss' })
  await ui.unmount()
  expect(w.notices).toContain(V.barDismissedNote)
  expect(await barShown($)).toBe(false)
  expect(text(await $.command.run(cmd('vigil-resume')))).toBe(V.resumed)
  ui = await $.ui.mount(BAND())
  expect(await ui.find({ type: 'Text', text: /context 41% · threshold 35%/ })).toBeDefined()
  await ui.unmount()
})

test('resume after a pause past the threshold shows the nudge now, and the ladder moves on', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.command.run(cmd('vigil-pause'))
  await $.session.measure(measure(41))
  await $.command.run(cmd('vigil-resume'))
  expect(await barShown($)).toBe(true)
  expect(w.state.get('context-vigil-mod.lastNudged')).toBe(40)
  expect(await pausedLine($)).toBe(false)
})

test('resume when vigil is already on says so', async ($, on) => {
  world(on)
  await $.session.start(START)
  expect(text(await $.command.run(cmd('vigil-resume')))).toBe(V.alreadyOn)
})

test('the paused line has the lowest precedence: a draft wait wins', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.command.run(cmd('vho'))
  await w.clock.settle()
  w.draft.value = 'half a sen'
  await $.tool.call(call)
  await w.clock.settle()
  await $.command.run(cmd('vigil-pause'))   // an explicit request's clear is not a threshold one: it still waits on the draft
  const ui = await $.ui.mount(BAND())
  expect(await ui.find({ type: 'Text', text: /Auto-clear paused while you're typing/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /vigil paused/ })).toBeUndefined()
  await ui.unmount()
})
