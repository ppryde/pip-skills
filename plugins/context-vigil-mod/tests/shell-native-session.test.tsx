import { expect, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import { V } from '../plugin/core/voice'
import { START, endInto, human, turn, world, type World } from './world'

// PROBES §16: where an organization manages Claude Code no classic.* event reaches a mod it does not
// list. The world here delivers none (it registers no classic hook): session.end and the id change
// drive everything.

const TOOL = 'mcp__context-vigil-mod__vigil_handover'
const FILE = '/cfg/context-vigil-mod/handovers/s1-1.md'
const call = (extra: Record<string, unknown> = {}) => ({ tool: TOOL, tool_use_id: 'h1', goal: 'G', state: 'S', next_step: 'N', session_name: 'Fix the bar', ...extra })
const vho = { command: 'vho', args: '', origin: { kind: 'composer' } as never } as never
const agent = (text: string) => ({ text, wait: false, origin: { kind: 'task-notification' } as never })
const events = (w: World) => [...w.files].filter(([k]) => k.includes('/events/')).map(([, t]) => t).join('')
const resumes = (w: World) => w.submits.filter(s => s.text.includes('Resume from the handover below'))
const iso = (ms: number) => new Date(ms).toISOString()

// A requested handover written and its clear issued; the clear stays queued until released.
async function handoverQueued($: Engine, w: World) {
  w.clearHold.held = true
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.command.run(vho)
  await w.clock.settle()
  await $.prompt.submit(human('and check the tests'))   // sent while the handover is being written
  await $.tool.call(call({ standing: 'Never cd into worktrees' }) as never)
  await w.clock.settle()
  expect(w.commands).toContain('clear')
}

test('the whole clear → resume loop with no classic event: read, resume, orders, name, held prompts', async ($, on) => {
  const w = world(on)
  w.titles.set(w.transcriptOf('s1'), 'My work')
  await handoverQueued($, w)
  expect(await $.prompt.submit(agent('agent X finished'))).toMatchObject({ drop: V.heldForClear })
  w.clearHold.release()
  await w.clock.settle()
  await endInto($, w, 'clear', { to: 's2' })
  await w.clock.advance(500)
  const text = resumes(w).at(-1)?.text ?? ''
  expect(resumes(w)).toHaveLength(1)
  expect(text).toContain(`(saved at ${FILE})`)
  expect(text).toContain('## Goal')   // the handover itself rides in the prompt: no file read to stall on (I1)
  expect(text).toContain('## Sent during handover')
  expect(text).toContain('> and check the tests')
  expect(text).toContain('> agent X finished')
  expect(w.submits.filter(s => s.text.includes('agent X finished'))).toHaveLength(1)
  expect(w.store.get('standing:s2')).toEqual(['Never cd into worktrees'])
  expect(w.store.has('standing:s1')).toBe(false)
  expect(w.store.has('pending:s1')).toBe(false)
  expect(w.renames).toEqual(['Archive: My work', 'My work'])
  expect(w.titles.get(w.transcriptOf('s2'))).toBe('My work')
  expect(events(w)).toContain('"kind":"resume"')
})

test('a /clear of your own moves the stranded mark to the new id', async ($, on) => {
  const w = world(on, { store: { 'stranded:s1': { name: 'My work', at: 1 } } })
  await $.session.start(START)
  await endInto($, w, 'clear', { to: 's2' })
  expect(w.store.get('stranded:s2')).toMatchObject({ name: 'My work', at: 1_000_000 })
  expect(w.store.has('stranded:s1')).toBe(false)
})

test('the session.end hook returns at once: the new id is waited for from a timer', async ($, on) => {
  const w = world(on)
  await handoverQueued($, w)
  w.clearHold.release()
  await w.clock.settle()
  const r = await $.session.end({ reason: 'clear', sessionId: 's1', resume: { id: 's1' } })
  expect(r).toEqual({ sessionId: 's1' })
  expect(w.store.has('pending:s1')).toBe(true)      // nothing handled inside the end's bound
})

test('a slow id change is polled for: nothing happens until the new id is there', async ($, on) => {
  const w = world(on)
  await handoverQueued($, w)
  w.clearHold.release()
  await w.clock.settle()
  await $.session.end({ reason: 'clear', sessionId: 's1', resume: { id: 's1' } })
  await w.clock.advance(600)                          // a /resume-like lag: the engine still answers s1
  expect(w.store.has('pending:s1')).toBe(true)
  expect(resumes(w)).toHaveLength(0)
  w.wipe()
  w.sessionId.value = 's2'
  w.liveId.value = 's2'
  await w.clock.advance(50)
  expect(w.store.has('pending:s1')).toBe(false)
  await w.clock.advance(500)
  expect(resumes(w)).toHaveLength(1)
  expect(w.store.get('standing:s2')).toEqual(['Never cd into worktrees'])
})

test('an id that never moves: the wait gives up, says so, and the handover still resumes', async ($, on) => {
  const w = world(on)
  await handoverQueued($, w)
  w.clearHold.release()
  await w.clock.settle()
  await endInto($, w, 'clear', { unmoved: true })
  expect(events(w)).toContain('"reason":"session-id-unmoved"')
  expect(w.logs.some(l => l.includes('session id not rebound'))).toBe(true)
  await w.clock.advance(500)
  expect(resumes(w)).toHaveLength(1)
  expect(w.store.get('standing:s1')).toEqual(['Never cd into worktrees'])   // no successor to move them to
})

test('a /resume rebinds: the old session\'s handover is never resumed, the new one\'s is offered', async ($, on) => {
  const theirs = { session: 's2', path: '/cfg/context-vigil-mod/handovers/s2-1.md', name: 'N', reason: 'request', markdown: '# s2', resume: true, followUp: null, createdAt: 1_000_000 }
  const w = world(on, { store: { 'pending:s2': theirs } })
  await handoverQueued($, w)
  w.clearHold.release()
  await w.clock.settle()
  await endInto($, w, 'resume', { to: 's2' })
  await w.clock.advance(1000)
  expect(resumes(w)).toHaveLength(0)
  expect(w.notices).toContain(V.pendingOffer(theirs.path))
  expect(w.state.get('context-vigil-mod.pending')).toMatchObject({ session: 's2' })
  await $.command.run(vho)
  await w.clock.settle()
  expect([...w.files.keys()].some(k => k.includes('/events/') && k.endsWith('/s2.jsonl'))).toBe(true)   // logged as s2 now
})

test('the drift guard: a change no session.end announced (a fork) is followed at the next turn, as a resume', async ($, on) => {
  const theirs = { session: 's2', path: '/cfg/context-vigil-mod/handovers/s2-1.md', name: 'N', reason: 'request', markdown: '# s2', resume: true, followUp: null, createdAt: 1_000_000 }
  const w = world(on, { store: { 'pending:s2': theirs } })
  await $.session.start(START)
  w.wipe()
  w.sessionId.value = 's2'
  await $.turn.start({ text: 'hello', turnId: 't1' })
  expect(w.notices).toContain(V.pendingOffer(theirs.path))
  expect(w.store.has('pending:s2')).toBe(true)   // offered, not consumed: a resume never clears into it
})

test('the drift guard runs on prompt.submit too while an end waits, before the prompt is judged', async ($, on) => {
  const theirs = { session: 's2', path: '/cfg/context-vigil-mod/handovers/s2-1.md', name: 'N', reason: 'request', markdown: '# s2', resume: true, followUp: null, createdAt: 1_000_000 }
  const w = world(on, { store: { 'stranded:s1': { name: 'My work', at: 1 }, 'pending:s2': theirs } })
  await $.session.start(START)
  await $.session.end({ reason: 'resume', sessionId: 's1', resume: { id: 's1' } })
  w.wipe()
  w.sessionId.value = 's2'
  const r = await $.prompt.submit(human('hello'))
  expect(r).not.toHaveProperty('drop')
  expect(w.notices).toContain(V.pendingOffer(theirs.path))
  expect(w.store.has('stranded:s1')).toBe(true)   // a resume moves no mark: only a clear does
})

test('no double handling: the drift guard gets there first, the end\'s poll then finds nothing to do', async ($, on) => {
  const w = world(on)
  await handoverQueued($, w)
  w.clearHold.release()
  await w.clock.settle()
  await $.session.end({ reason: 'clear', sessionId: 's1', resume: { id: 's1' } })
  w.wipe()
  w.sessionId.value = 's2'
  w.liveId.value = 's2'
  await $.turn.start({ text: '', turnId: 't1' })   // before the poll's timer: the guard handles it, as the clear it was
  await w.clock.advance(1000)
  expect(resumes(w)).toHaveLength(1)
  expect(events(w).split('"kind":"resume"').length - 1).toBe(1)
  expect(w.store.get('standing:s2')).toEqual(['Never cd into worktrees'])
})

test('two triggers for one change: two ends for one clear resume once', async ($, on) => {
  const w = world(on)
  await handoverQueued($, w)
  w.clearHold.release()
  await w.clock.settle()
  await $.session.end({ reason: 'clear', sessionId: 's1', resume: { id: 's1' } })
  await $.session.end({ reason: 'clear', sessionId: 's1', resume: { id: 's1' } })
  w.wipe()
  w.sessionId.value = 's2'
  w.liveId.value = 's2'
  await w.clock.advance(1000)
  expect(resumes(w)).toHaveLength(1)
})

test('an exit is not a change of conversation: nothing is polled or handled', async ($, on) => {
  const w = world(on)
  await handoverQueued($, w)
  await $.session.end({ reason: 'prompt_input_exit', sessionId: 's1', resume: { id: 's1' } })
  w.sessionId.value = 's2'
  await w.clock.advance(6000)
  expect(w.store.has('pending:s1')).toBe(true)
  expect(events(w)).not.toContain('session-id-unmoved')
})

// No StopFailure reaches the mod and turn.complete names no error kind (PROBES §16): read off the
// limit windows. A full one latches to its reset, one at 90% or more briefly (I5), under that nothing.
test('a turn an API error ended near a limit latches briefly, and the latch lifts by itself (I5)', async ($, on) => {
  const w = world(on, { now: 1_000_000 })
  await $.session.start(START)
  w.rateLimits.value = [{ kind: 'five_hour', percentUsed: 92, resetsAt: iso(1_000_000 + 3_600_000) }]
  await $.turn.complete({ ...turn('e1'), reason: 'error' })
  expect(w.store.get('latch')).toEqual({ kind: 'unknown', resetsAtMs: 1_000_000 + 300_000 })
  await w.clock.advance(301_000)
  expect(w.store.get('latch')).toBeUndefined()
})

test('a turn an API error ended latches to the reset when a limit window reads full, and not far from one', async ($, on) => {
  const w = world(on, { now: 1_000_000 })
  await $.session.start(START)
  w.rateLimits.value = [{ kind: 'five_hour', percentUsed: 80, resetsAt: iso(1_000_000 + 3_600_000) }]
  await $.turn.complete({ ...turn('e1'), reason: 'error' })
  expect(w.store.get('latch')).toBeUndefined()
  w.rateLimits.value = [{ kind: 'five_hour', percentUsed: 100, resetsAt: iso(1_000_000 + 3_600_000) }]
  await $.turn.complete({ ...turn('e2'), agentId: 'sub', reason: 'error' })   // a subagent's error is not the session's
  expect(w.store.get('latch')).toBeUndefined()
  await $.turn.complete({ ...turn('e3'), reason: 'error' })
  expect(w.store.get('latch')).toEqual({ kind: 'five_hour', resetsAtMs: 1_000_000 + 3_600_000 })
})

test('a poll that finds the drift guard mid-handler looks again, and still follows the clear (I3)', async ($, on) => {
  const theirs = { session: 's2', path: '/cfg/context-vigil-mod/handovers/s2-1.md', name: 'N', reason: 'request', markdown: '# from s2', resume: true, followUp: null, createdAt: 1_000_000 }
  const w = world(on, { store: { 'pending:s2': theirs } })
  await $.session.start(START)
  let release = () => {}
  w.fsRead.gate = new Promise<void>(r => { release = r })
  w.wipe()
  w.sessionId.value = 's2'
  void $.turn.start({ text: '', turnId: 'fork' })   // the drift guard follows a fork into s2: it is held mid-handler
  await w.clock.settle()
  await $.session.end({ reason: 'clear', sessionId: 's2', resume: { id: 's2' } })
  w.wipe()
  w.sessionId.value = 's3'
  await w.clock.advance(0)                          // the poll finds s3 while the guard is still busy
  w.fsRead.gate = null
  release()
  await w.clock.settle()
  await w.clock.advance(50)
  await w.clock.advance(500)
  expect(resumes(w).at(-1)?.text).toContain('# from s2')
  expect(w.store.has('pending:s2')).toBe(false)
})

test('an id that moves after the wait gave up: the drift guard finishes the clear (M1)', async ($, on) => {
  const w = world(on, { store: { 'stranded:s1': { name: 'My work', at: 1 } } })
  await handoverQueued($, w)
  w.clearHold.release()
  await w.clock.settle()
  await endInto($, w, 'clear', { unmoved: true })   // handled on s1; its resume is on its 500 ms timer
  expect(w.store.get('standing:s1')).toEqual(['Never cd into worktrees'])
  w.wipe()
  w.sessionId.value = 's2'
  await $.turn.start({ text: '', turnId: 'late' })
  expect(w.store.get('standing:s2')).toEqual(['Never cd into worktrees'])
  expect(w.store.has('standing:s1')).toBe(false)
  expect(w.store.get('stranded:s2')).toMatchObject({ name: 'My work' })
  expect(events(w)).toContain('session-id-late')
  await w.clock.advance(500)
  expect(resumes(w)).toHaveLength(1)                // the retrying resume was left alone
})

test('the drift guard on prompt.submit handles a clear and the same prompt carries its handover (C1)', async ($, on) => {
  const w = world(on)
  await handoverQueued($, w)
  w.clearHold.release()
  await w.clock.settle()
  await $.session.end({ reason: 'clear', sessionId: 's1', resume: { id: 's1' } })
  w.wipe()
  w.sessionId.value = 's2'
  w.liveId.value = 's2'
  await $.prompt.submit(human('hello again'))       // before the poll's timer
  await w.clock.advance(1000)
  const theirs = w.submits.find(s => s.text.startsWith('hello again'))
  expect(theirs?.text).toContain('## Goal')
  expect(resumes(w)).toHaveLength(0)
  expect(w.submits.filter(s => s.text.includes('## Goal'))).toHaveLength(1)
})

// I4: the transcript is where the session started, not where its cwd moved to.
test('a moved cwd: the transcript is still read from the cwd the session was bound in', async ($, on) => {
  const w = world(on)
  const bound = '/cfg/projects/-repo/s1.jsonl'
  w.files.set(bound, '{}\n')
  w.titles.set(bound, 'My work')
  await $.session.start(START)
  w.cwd.value = '/repo/.claude/worktrees/x'
  await $.command.run(vho)
  await w.clock.settle()
  await $.tool.call(call() as never)
  await w.clock.settle()
  expect(w.greps.at(0)?.at(-1)).toBe(bound)
  expect(w.renames[0]).toBe('Archive: My work')
})

test('a moved cwd with no transcript where it started: the live cwd is tried', async ($, on) => {
  const w = world(on)
  const live = '/cfg/projects/-repo--claude-worktrees-x/s1.jsonl'
  w.titles.set(live, 'My work')
  await $.session.start(START)
  w.cwd.value = '/repo/.claude/worktrees/x'
  await $.command.run(vho)
  await w.clock.settle()
  await $.tool.call(call() as never)
  await w.clock.settle()
  expect(w.greps.at(0)?.at(-1)).toBe(live)
  expect(w.renames[0]).toBe('Archive: My work')
})
