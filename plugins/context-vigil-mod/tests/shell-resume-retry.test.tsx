import { expect, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import { V } from '../plugin/core/voice'
import { START, human, world, type World, endInto } from './world'

const TOOL = 'mcp__context-vigil-mod__vigil_handover'
const call = { tool: TOOL, tool_use_id: 'h1', goal: 'G', state: 'S', next_step: 'N', session_name: 'Name' } as never
const vho = { command: 'vho', args: '', origin: { kind: 'composer' } as never } as never
const events = (w: World) => [...w.files.entries()].filter(([k]) => k.includes('/events/')).map(([, v]) => v).join('')
const resumes = (w: World) => w.submits.filter(s => s.text.includes('Resume from the handover below'))

// A /vho through to the clear; returns once SessionStart has run on the new session.
async function cleared($: Engine, w: World) {
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.command.run(vho)
  await w.clock.settle()
  await $.tool.call(call)
  await w.clock.settle()
  w.sessionId.value = 's2'
  await endInto($, w, 'clear')
}

test('a resume refused while the session is still starting is retried and lands once', async ($, on) => {
  const w = world(on)
  await cleared($, w)
  w.submitFails.count = 2
  await w.clock.advance(500)    // first attempt: refused
  expect(resumes(w)).toHaveLength(0)
  await w.clock.advance(1000)   // second: refused
  expect(resumes(w)).toHaveLength(0)
  await w.clock.advance(2000)   // third: accepted
  expect(resumes(w)).toHaveLength(1)
  await w.clock.advance(60_000)
  expect(resumes(w)).toHaveLength(1)   // never twice
  const log = events(w)
  expect(log.match(/"reason":"resume-retry"/g)).toHaveLength(2)
  expect(log).toContain('"kind":"resume.sent"')
  expect(log).toContain('"attempt":3')
})

test('a resume accepted at once logs no retry', async ($, on) => {
  const w = world(on)
  await cleared($, w)
  await w.clock.advance(500)
  expect(resumes(w)).toHaveLength(1)
  expect(events(w)).not.toContain('resume-retry')
  expect(events(w)).toContain('"kind":"resume.sent"')
})

test('five refusals in a row (about 15.5 s) give up with the existing notice', async ($, on) => {
  const w = world(on)
  await cleared($, w)
  w.submitFails.count = 99
  await w.clock.advance(15_500)
  expect(resumes(w)).toHaveLength(0)
  expect(w.notices.some(n => n.startsWith(V.resumeFailed('/cfg/context-vigil-mod/handovers/s1-1.md', null).slice(0, 12)))).toBe(true)
  expect(events(w)).toContain('resume-rejected')
  expect(events(w).match(/"reason":"resume-retry"/g)).toHaveLength(5)
  w.submitFails.count = 0
  await w.clock.advance(60_000)
  expect(resumes(w)).toHaveLength(0)   // the chain has ended
})

test('the person typing in the meantime cancels the retry: their prompt wins, and carries the handover once (C1)', async ($, on) => {
  const w = world(on)
  await cleared($, w)
  w.submitFails.count = 1
  await w.clock.advance(500)
  await $.prompt.submit(human('pick up the handover'))
  w.submitFails.count = 0
  await w.clock.advance(60_000)
  expect(resumes(w)).toHaveLength(0)
  const theirs = w.submits.filter(s => s.text.startsWith('pick up the handover'))
  expect(theirs).toHaveLength(1)
  expect(theirs[0]?.text).toContain('(saved at /cfg/context-vigil-mod/handovers/s1-1.md)')
  expect(theirs[0]?.text).toContain('## Goal')
  expect(w.submits.filter(s => s.text.includes('## Goal'))).toHaveLength(1)   // exactly once
  expect(w.notices.some(n => n.includes("Couldn't resume"))).toBe(false)
  await $.prompt.submit(human('next thing'))
  expect(w.submits.at(-1)?.text).toBe('next thing')   // spent: the next prompt carries nothing
})

test('a slash command in the retry window leaves the resume alone: the handover still reaches the model once', async ($, on) => {
  const w = world(on)
  await cleared($, w)
  w.submitFails.count = 1
  await w.clock.advance(500)                       // refused: retrying
  await $.prompt.submit({ ...human('/rename x'), command: { name: 'rename', args: 'x' } } as never)
  w.submitFails.count = 0
  await w.clock.advance(60_000)
  expect(resumes(w)).toHaveLength(1)
  expect(w.submits.filter(s => s.text.includes('## Goal'))).toHaveLength(1)
  expect(w.notices.some(n => n.includes("Couldn't resume"))).toBe(false)
})

test('a prompt the mod drops (a plain-words handover request) gives the owed resume back (C1)', async ($, on) => {
  const w = world(on)
  await cleared($, w)
  await $.prompt.submit(human('do a handover'))
  await w.clock.advance(1000)
  expect(resumes(w)).toHaveLength(1)
})

test('a plugin prompt in the meantime does not cancel it', async ($, on) => {
  const w = world(on)
  await cleared($, w)
  w.submitFails.count = 1
  await w.clock.advance(500)
  await $.prompt.submit({ text: 'something else', wait: false, origin: { kind: 'plugin' } as never })
  await w.clock.advance(5000)
  expect(resumes(w)).toHaveLength(1)
})

test('a first events write that fails is said once, not on every line', async ($, on) => {
  const w = world(on)
  w.eventsWriteRefused.value = true
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.command.run(vho)
  await w.clock.settle()
  await $.tool.call(call)
  await w.clock.settle()
  const said = w.logs.filter(l => l.includes('event log'))
  expect(said.length).toBeGreaterThanOrEqual(1)
  const perPath = new Set(said.map(l => l.match(/\/[^ ]*\.jsonl?/)?.[0]))
  expect(said).toHaveLength(perPath.size)   // one line per path
})

test('a clear whose new session id is not yet rebound is said, not silent', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.command.run(vho)
  await w.clock.settle()
  await $.tool.call(call)
  await w.clock.settle()
  // the engine has not rebound the id yet: it still answers the old one
  await endInto($, w, 'clear')
  expect(w.logs.some(l => l.includes('not rebound') && l.includes('still s1'))).toBe(true)
  await w.clock.advance(500)
  expect(resumes(w)).toHaveLength(1)
})

test('a retry still waiting does not survive a /resume or a second /clear into another conversation', async ($, on) => {
  const w = world(on)
  await cleared($, w)
  w.submitFails.count = 1
  await w.clock.advance(500)          // refused: retrying
  w.sessionId.value = 's3'
  await endInto($, w, 'resume')
  await w.clock.advance(60_000)
  expect(resumes(w)).toHaveLength(0)
})
