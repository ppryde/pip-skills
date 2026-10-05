import { expect, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import { V } from '../core/voice'
import { START, human, turn, world, type World } from './world'

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

test('the handover crosses the $.state wipe: inject, rename, resume — and is spent', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run(vho)
  await w.clock.settle()
  await $.tool.call(call({ session_name: 'Fix the bar' }) as never)
  await w.clock.settle()
  expect(w.commands).toContain('clear')
  w.sessionId.value = 's2'
  const ss = await $.classic.SessionStart({ source: 'clear', transcript_path: '/t/s2.jsonl' } as never)
  expect(w.state.get(PENDING)).toBeUndefined()
  expect(ss.additionalContext?.join('\n')).toContain('## Goal')
  await w.clock.advance(500)
  expect(w.renames).toEqual(['Fix the bar'])
  expect(w.submits.at(-1)?.text).toContain('Resume from the handover')
  w.sessionId.value = 's3'
  const again = await $.classic.SessionStart({ source: 'clear' } as never)
  expect(again.additionalContext ?? []).toEqual([])           // the stored copy was deleted
})

test('the person present before a clear is still present after it: no armed handover', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await $.session.start(START)
  await $.prompt.submit(human('still here'))
  w.sessionId.value = 's2'
  await $.classic.SessionStart({ source: 'clear' } as never)
  await $.tool.call({ tool: 'Bash', tool_use_id: 'b', command: 'ls' } as never)
  expect(w.state.get('context-vigil-mod.mode')).toBe('attended')
  await $.session.measure(measure(36))
  await w.clock.settle()
  expect(w.submits.some(s => s.text.includes(TOOL))).toBe(false)
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
  await $.turn.start({ text: w.submits.at(-1)?.text ?? '', turnId: 'a' } as never)
  await $.turn.complete(turn('a'))
  await w.clock.settle()
  expect(w.submits.filter(s => s.text.includes(TOOL)).length).toBe(2)
  await $.turn.start({ text: w.submits.at(-1)?.text ?? '', turnId: 'b' } as never)
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
  await $.session.measure(measure(20))
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
  await $.session.measure(measure(20))
  await $.session.measure(measure(36))
  await w.clock.settle()
  expect(w.submits.at(-1)?.text).toContain(TOOL)
})

const eventLog = (w: World) => [...w.files.entries()].find(([k]) => k.includes('/events/'))?.[1] ?? ''

// Auto mode, baseline read, then the threshold crosses and the instruction goes out.
async function autoHandoverInFlight($: Engine, w: World) {
  await $.session.start(START)
  await $.prompt.submit(human('go'))
  await w.clock.advance(31 * MIN)
  await $.tool.call({ tool: 'Bash', tool_use_id: 'b', command: 'ls' } as never)
  await $.session.measure(measure(20))
  await $.session.measure(measure(36))
  await w.clock.settle()
  expect(w.submits.at(-1)?.text).toContain(TOOL)
}

test('a human prompt during an auto handover: the handover is kept, nothing clears, the person is told', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await autoHandoverInFlight($, w)
  await $.prompt.submit(human('hold on'))
  await $.tool.call(call() as never)
  await w.clock.settle()
  await w.clock.advance(60_000)
  expect(w.commands).not.toContain('clear')
  expect(w.state.get(PENDING)).toMatchObject({ reason: 'threshold' })
  expect(w.notices).toContain('📜 Handover saved — you came back, so nothing was cleared; /vho or /clear when you are ready')
  expect(eventLog(w)).toContain('"clear.skipped"')
  expect(eventLog(w)).toContain('"attended"')
})

test('a requested handover is attended by definition: a prompt does not stop its clear', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.command.run(vho)
  await w.clock.settle()
  await $.prompt.submit(human('carry on'))
  await $.tool.call(call() as never)
  await w.clock.settle()
  expect(w.commands).toContain('clear')
})

test('auto mode holds back a handover until context has grown a step above the baseline', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true, nudgeAt: 25 } } })
  await $.session.start(START)
  await $.prompt.submit(human('go'))
  await w.clock.advance(31 * MIN)
  await $.tool.call({ tool: 'Bash', tool_use_id: 'b', command: 'ls' } as never)
  await $.session.measure(measure(24))
  await $.session.measure(measure(26))
  await w.clock.settle()
  expect(w.submits.map(s => s.text).join('\n')).not.toContain(TOOL)
  expect(eventLog(w)).toContain('"guard.baseline"')
  await $.session.measure(measure(29))
  await w.clock.settle()
  expect(w.submits.at(-1)?.text).toContain(TOOL)
})

test('a clear gives the new session its own baseline', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true, nudgeAt: 25 } } })
  await $.session.start(START)
  await $.prompt.submit(human('go'))
  await w.clock.advance(31 * MIN)
  await $.tool.call({ tool: 'Bash', tool_use_id: 'b', command: 'ls' } as never)
  await $.session.measure(measure(10))
  await $.classic.SessionStart({ source: 'clear' } as never)
  await $.session.measure(measure(24))
  await $.session.measure(measure(26))
  await w.clock.settle()
  expect(w.submits.map(s => s.text).join('\n')).not.toContain(TOOL)
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
  await $.classic.SessionStart({ source: 'clear', transcript_path: '/t/s2.jsonl' } as never)
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
  await $.classic.SessionStart({ source: 'clear', transcript_path: '/t/s2.jsonl' } as never)
  await w.clock.advance(500)
  expect(w.notices).toContain("🏷️ couldn't name the new session — carrying on")
  expect(w.submits.at(-1)?.text).toContain('Resume from the handover')
})

async function handoverThenClear($: any, w: World, transcript: string | null = '/t/s2.jsonl') {
  await $.session.start(START)
  await $.command.run(vho)
  await w.clock.settle()
  await $.tool.call(call({ session_name: 'Fix the bar' }) as never)
  await w.clock.settle()
  w.commands.length = 0
  w.sessionId.value = 's2'
  await $.classic.SessionStart({ source: 'clear', transcript_path: transcript ?? undefined } as never)
  await w.clock.advance(500)
}

test('an unnamed old session is renamed, and the grep targets its own transcript', async ($, on) => {
  const w = world(on)
  await handoverThenClear($, w)
  expect(w.renames).toEqual(['Fix the bar'])
  expect(w.greps).toEqual([['grep', '-c', '-F', '"type":"custom-title"', '/t/s1.jsonl']])
})

test('an already-named old session keeps its name: no rename, resume still submitted', async ($, on) => {
  const w = world(on)
  w.titled.add('/t/s1.jsonl')
  await handoverThenClear($, w)
  expect(w.commands).not.toContain('rename')
  expect(w.submits.at(-1)?.text).toContain('Resume from the handover')
})

test('a failed name check neither renames nor notifies, and still resumes', async ($, on) => {
  const w = world(on)
  w.grepFails.value = true
  await handoverThenClear($, w)
  expect(w.commands).not.toContain('rename')
  expect(w.notices.some(n => n.includes('couldn'))).toBe(false)
  expect(w.submits.at(-1)?.text).toContain('Resume from the handover')
})

test('no transcript path means the name is unknown: no rename', async ($, on) => {
  const w = world(on)
  await handoverThenClear($, w, null)
  expect(w.commands).not.toContain('rename')
  expect(w.greps).toEqual([])
})

test('a stored handover with no name resumes without any rename', async ($, on) => {
  const old = { session: 's1', path: '/cfg/context-vigil-mod/handovers/s1-1.md', reason: 'request', markdown: '# OLD', resume: true, followUp: null, createdAt: 1_000_000 }
  const w = world(on, { store: { 'pending:s1': old } })
  await $.session.start(START)
  await $.classic.SessionStart({ source: 'clear' } as never)
  await w.clock.advance(500)
  expect(w.commands).not.toContain('rename')
  expect(w.notices.some(n => n.includes('couldn'))).toBe(false)
  expect(w.submits.at(-1)?.text).toContain('Resume from the handover')
})

test('a clear that lands while a handover is awaited abandons it: the next turn submits nothing', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run(vho)
  await w.clock.settle()
  expect(w.state.get('context-vigil-mod.awaiting')).toMatchObject({ started: true })
  const before = w.submits.length
  w.sessionId.value = 's2'
  await $.classic.SessionStart({ source: 'clear' } as never)
  expect(w.state.get('context-vigil-mod.awaiting')).toBeNull()
  await $.turn.complete(turn('fresh'))
  await w.clock.settle()
  expect(w.submits.length).toBe(before)
  expect(w.notices).not.toContain("📜 Couldn't write a handover — nothing was cleared")
})

test('a rejected instruction submit fails visibly instead of stalling', async ($, on) => {
  const w = world(on)
  w.submitRefused.value = true
  await $.session.start(START)
  await $.command.run(vho)
  await w.clock.settle()
  expect(w.notices).toContain("📜 Couldn't write a handover — nothing was cleared")
  expect(w.state.get('context-vigil-mod.awaiting')).toBeNull()
  expect([...w.files.values()].join('')).toContain('submit-rejected')
})

test('a clear forgets the day-log cache and the edited files', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.tool.call({ tool: 'Edit', tool_use_id: 'e', file_path: '/repo/old.ts' } as never)
  await $.session.measure(measure(36))
  const day = [...w.files.keys()].find(k => k.includes('/events/'))
  expect(day).toBeDefined()
  w.files.delete(day ?? '')
  await $.classic.SessionStart({ source: 'clear' } as never)
  await $.session.measure(measure(36))
  expect((w.files.get(day ?? '') ?? '').split('\n').filter(l => l.includes('"threshold"')).length).toBe(1)   // a stale cache would rewrite the old line too
  await $.command.run(vho)
  await w.clock.settle()
  await $.tool.call(call() as never)
  expect(w.files.get('/cfg/context-vigil-mod/handovers/s1-1.md')).not.toContain('/repo/old.ts')
})

test('a pending handover with turns since it was written is not reused: /vho writes a fresh one', async ($, on) => {
  const w = world(on)
  w.clearRefused.value = true
  await $.session.start(START)
  await $.command.run(vho)
  await w.clock.settle()
  await $.tool.call(call({ state: 'OLD STATE' }) as never)
  await w.clock.settle()
  w.clearRefused.value = false
  for (let i = 0; i < 3; i++) {
    await w.clock.advance(10 * MIN)
    await $.prompt.submit(human(`more work ${i}`))
    await $.turn.complete(turn(`w${i}`))
  }
  await $.command.run(vho)
  await w.clock.settle()
  expect(w.submits.filter(s => s.text.includes(TOOL)).length).toBe(2)
  expect(w.commands).not.toContain('clear')
  await $.tool.call(call({ state: 'NEW STATE' }) as never)
  await w.clock.settle()
  expect(w.commands).toContain('clear')
  w.sessionId.value = 's2'
  const ss = await $.classic.SessionStart({ source: 'clear' } as never)
  expect(ss.additionalContext?.join('\n')).toContain('NEW STATE')
  expect(ss.additionalContext?.join('\n')).not.toContain('OLD STATE')
})

test('a pending handover with no turn since it was written is reused: /vho clears at once', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run(vho)
  await w.clock.settle()
  w.draft.value = 'half a sen'
  await $.tool.call(call() as never)
  await $.turn.complete(turn('instruction'))
  await w.clock.settle()
  expect(w.commands).not.toContain('clear')
  w.draft.value = ''
  await $.command.run(vho)
  await w.clock.settle()
  expect(w.submits.filter(s => s.text.includes(TOOL)).length).toBe(1)
  expect(w.commands).toContain('clear')
})

test('a hot reload picks a clear parked on a draft back up instead of stranding it', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run(vho)
  await w.clock.settle()
  w.draft.value = 'half a sen'
  await $.tool.call(call() as never)
  await w.clock.settle()
  await $.session.start(START)          // the reload: same session, $.state kept, timers gone
  w.draft.value = ''
  await w.clock.advance(5000)
  expect(w.commands).toContain('clear')
})

test('a hot reload with a stale pending handover offers it instead of clearing', async ($, on) => {
  const w = world(on)
  w.clearRefused.value = true
  await $.session.start(START)
  await $.command.run(vho)
  await w.clock.settle()
  await $.tool.call(call() as never)
  await w.clock.settle()
  w.clearRefused.value = false
  await w.clock.advance(10 * MIN)
  await $.turn.complete(turn('later'))
  w.notices.length = 0
  await $.session.start(START)
  await w.clock.advance(5000)
  expect(w.commands).not.toContain('clear')
  expect(w.notices).toContain('📜 A handover is waiting (/cfg/context-vigil-mod/handovers/s1-1.md) — /clear to resume from it')
})

test('a reload counts as presence: auto mode does not hand over at the next agent step', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await $.session.start(START)
  await $.tool.call({ tool: 'Bash', tool_use_id: 'b', command: 'ls' } as never)
  await $.session.measure(measure(36))
  await w.clock.settle()
  expect(w.submits.some(s => s.text.includes(TOOL))).toBe(false)
})

test('a rejected resume after a clear says so, naming the handover', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run(vho)
  await w.clock.settle()
  await $.tool.call(call() as never)
  await w.clock.settle()
  w.sessionId.value = 's2'
  await $.classic.SessionStart({ source: 'clear' } as never)
  w.submitRefused.value = true
  await w.clock.advance(500)
  expect(w.notices.some(n => n.includes("Couldn't resume") && n.includes('/cfg/context-vigil-mod/handovers/s1-1.md'))).toBe(true)
  expect([...w.files.values()].join('')).toContain('resume-rejected')
})

test('a handover file that cannot be written: a notice, no pending, no clear, and the model is told', async ($, on) => {
  const w = world(on)
  w.handoverWriteRefused.value = true
  await $.session.start(START)
  await $.command.run(vho)
  await w.clock.settle()
  const r = await $.tool.call(call() as never)
  await w.clock.settle()
  expect(String((r as { result?: unknown }).result)).toContain('not saved')
  expect(w.notices).toContain("📜 Couldn't write a handover — nothing was cleared")
  expect(w.state.get(PENDING) ?? null).toBeNull()
  expect(w.store.get('pending:s1')).toBeUndefined()
  expect(w.commands).not.toContain('clear')
  expect([...w.files.values()].join('')).toContain('write-failed')
})

// R1-01: the clear is tied to an `awaiting` the mod created.
test('R1-01: a handover tool call nobody asked for saves the file and never clears', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  const r = await $.tool.call(call() as never)
  await w.clock.settle()
  expect(String((r as { result?: unknown }).result)).toContain('nothing was cleared')
  expect(w.files.get('/cfg/context-vigil-mod/handovers/s1-1.md')).toContain('## Goal')
  expect(w.commands).not.toContain('clear')
  expect((w.state.get(PENDING) as { resume: boolean }).resume).toBe(false)
  expect(w.notices.length).toBeGreaterThan(0)
})

test('R1-01: a duplicate tool call after a requested handover does not clear a second time', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run(vho)
  await w.clock.settle()
  await $.tool.call(call() as never)
  await w.clock.settle()
  expect(w.commands.filter(c => c === 'clear')).toHaveLength(1)
  await $.tool.call(call({ tool_use_id: 'h2' }) as never)
  await w.clock.settle()
  expect(w.commands.filter(c => c === 'clear')).toHaveLength(1)
  expect(w.files.has('/cfg/context-vigil-mod/handovers/s1-2.md')).toBe(true)
})

// R1-02: only the instruction turn's own completion counts as a missed attempt.
const instructionTurn = ($: Engine, w: World, id: string) => $.turn.start({ text: w.submits.at(-1)?.text ?? '', turnId: id } as never)
const asked = (w: World) => w.submits.filter(s => s.text.includes(TOOL)).length

test('R1-02: a subagent turn ending is not a missed attempt', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run(vho)
  await w.clock.settle()
  await instructionTurn($, w, 'i1')
  await $.turn.complete({ ...turn('sub'), agentId: 'a1' } as never)
  await w.clock.settle()
  expect(asked(w)).toBe(1)
  expect(w.notices).not.toContain("📜 Couldn't write a handover — nothing was cleared")
})

test('R1-02: a main turn already in flight ending is not a missed attempt', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run(vho)
  await w.clock.settle()
  await $.turn.complete(turn('inflight'))     // started before the instruction; no turn.start of ours yet
  await w.clock.settle()
  expect(asked(w)).toBe(1)
})

test('R1-02: an interrupted instruction turn is not retried, and the interrupt is presence', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await $.session.start(START)
  await $.command.run(vho)
  await w.clock.settle()
  await instructionTurn($, w, 'i1')
  await $.turn.complete({ ...turn('i1'), isAborted: true, reason: 'aborted' } as never)
  await w.clock.settle()
  expect(asked(w)).toBe(1)
  expect(w.state.get('context-vigil-mod.awaiting')).toBeNull()
  expect(w.state.get('context-vigil-mod.mode')).toBe('attended')
  expect(w.notices.some(n => n.includes('interrupted'))).toBe(true)
})

// R1-04: a pending restored from $.store after a restart is only reusable while it is young.
test('R1-04: a day-old stored handover is not cleared into by /vho after a restart', async ($, on) => {
  const old = { session: 's1', path: '/cfg/context-vigil-mod/handovers/s1-1.md', name: 'Old', reason: 'request', markdown: '# old', resume: true, followUp: null, createdAt: 100_000_000 - 86_400_000 }
  const w = world(on, { now: 100_000_000, store: { 'pending:s1': old } })
  await $.session.start(START)
  await $.command.run(vho)
  await w.clock.settle()
  expect(w.commands).not.toContain('clear')
  expect(w.submits.filter(s => s.text.includes(TOOL))).toHaveLength(1)
})

// R1-10: a manual /clear injects a parked handover, but the mod's own resume needs it fresh and no latch.
async function parkHandover($: Engine, w: World) {
  w.clearRefused.value = true
  await $.session.start(START)
  await $.command.run(vho)
  await w.clock.settle()
  await $.tool.call(call() as never)
  await w.clock.settle()
  expect(w.state.get(PENDING)).toBeTruthy()
  w.clearRefused.value = false
}
const resumeSubmits = (w: World) => w.submits.filter(s => s.text.includes('Resume from the handover'))

test('R1-10: a manual /clear after later turns injects the handover but sends no automatic resume', async ($, on) => {
  const w = world(on)
  await parkHandover($, w)
  await w.clock.advance(2 * MIN)
  await $.turn.complete(turn('t1'))
  await $.turn.complete(turn('t2'))
  w.notices.length = 0
  w.sessionId.value = 's2'
  const ss = await $.classic.SessionStart({ source: 'clear' } as never)
  await w.clock.advance(1000)
  expect(ss.additionalContext?.join('\n')).toContain('## Goal')
  expect(resumeSubmits(w)).toHaveLength(0)
  expect(w.notices.some(n => n.includes('no automatic resume'))).toBe(true)
})

test('R1-10: a fresh parked handover still resumes after a manual /clear', async ($, on) => {
  const w = world(on)
  await parkHandover($, w)
  await $.turn.complete(turn('instruction'))
  w.sessionId.value = 's2'
  await $.classic.SessionStart({ source: 'clear' } as never)
  await w.clock.advance(1000)
  expect(resumeSubmits(w)).toHaveLength(1)
})

test('R1-10: under the latch the handover is injected but the mod sends no resume', async ($, on) => {
  const w = world(on)
  await parkHandover($, w)
  w.store.set('latch', { kind: 'five_hour', resetsAtMs: 1_000_000 + 60 * MIN })
  w.notices.length = 0
  w.sessionId.value = 's2'
  const ss = await $.classic.SessionStart({ source: 'clear' } as never)
  await w.clock.advance(1000)
  expect(ss.additionalContext?.join('\n')).toContain('## Goal')
  expect(resumeSubmits(w)).toHaveLength(0)
  expect(w.notices.some(n => n.includes('usage limit is in force'))).toBe(true)
})

test('R1-10: the person\'s held text is sent even under the latch', async ($, on) => {
  const pending = { session: 's1', path: '/cfg/context-vigil-mod/handovers/s1-1.md', name: 'N', reason: 'last_light', markdown: '# h', resume: false, followUp: 'my own words', createdAt: 1_000_000 }
  const w = world(on, { store: { 'pending:s1': pending, latch: { kind: 'five_hour', resetsAtMs: 1_000_000 + 60 * MIN } } })
  await $.session.start(START)
  w.sessionId.value = 's2'
  await $.classic.SessionStart({ source: 'clear' } as never)
  await w.clock.advance(1000)
  expect(w.submits.map(s => s.text)).toContain('my own words')
})

// R1-08: an in-process /resume or fork is a different session.
test('R1-08: after an in-process /resume the handover is filed under the new session and s1\'s is never injected', async ($, on) => {
  const w = world(on)
  await parkHandover($, w)                              // s1's handover is parked
  w.sessionId.value = 's2'
  await $.classic.SessionStart({ source: 'resume' } as never)
  await $.command.run(vho)
  await w.clock.settle()
  expect(w.submits.filter(s => s.text.includes(TOOL))).toHaveLength(2)   // a fresh instruction, not a clear into s1's file
  expect(w.commands).not.toContain('clear')
  await $.tool.call(call() as never)
  await w.clock.settle()
  expect(w.files.has('/cfg/context-vigil-mod/handovers/s2-1.md')).toBe(true)
  expect(w.commands).toContain('clear')
  w.sessionId.value = 's3'
  const ss = await $.classic.SessionStart({ source: 'clear' } as never)
  const injected = ss.additionalContext?.join('\n') ?? ''
  expect(injected).toContain('Handover — s2')
  expect(injected).not.toContain('Handover — s1')
})

test('R1-11: a second /vho while one is in flight starts nothing new and says so', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.command.run(vho)
  await $.command.run(vho)
  await w.clock.settle()
  expect(w.submits.filter(x => x.text.includes(TOOL))).toHaveLength(1)
  expect(w.notices.some(n => n.includes('already in progress'))).toBe(true)
})

test('R1-18: a restarted session never overwrites an earlier handover file', async ($, on) => {
  const w = world(on, { files: { '/cfg/context-vigil-mod/handovers/s1-1.md': 'earlier' } })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.command.run(vho)
  await w.clock.settle()
  const r = await $.tool.call(call() as never)
  expect(String((r as { result?: unknown }).result)).toContain('/s1-2.md')
  expect(w.files.get('/cfg/context-vigil-mod/handovers/s1-1.md')).toBe('earlier')
})

test('a clear already in flight is not queued twice when the threshold crosses again (R2-10)', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  w.clearHold.held = true
  await autoHandoverInFlight($, w)
  await $.tool.call(call() as never)           // clear 1 is now queued and held
  await w.clock.settle()
  expect(w.commands.filter(c => c === 'clear').length).toBe(1)
  await $.session.measure(measure(46))         // the instruction turn's growth crosses the next step
  await w.clock.settle()
  w.clearHold.release()
  await w.clock.settle()
  expect(w.commands.filter(c => c === 'clear').length).toBe(1)
})

test('auto mode switched Off while an unattended clear waits stops it, with a notice (R2-08)', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await autoHandoverInFlight($, w)
  await $.tool.call(call() as never)
  w.draft.value = 'half a sen'                   // typed after the tool hook's own look at the box
  await w.clock.settle()
  expect(w.notices).toContain('✍️ Handover waiting — there is a draft in your prompt box')
  w.store.set('settings', { auto: false })      // another session, or /vsetup auto on the phone
  w.draft.value = ''
  await w.clock.advance(5000)
  expect(w.commands).not.toContain('clear')
  expect(w.notices).toContain('📜 Handover saved — auto mode was switched off, so nothing was cleared; /vho or /clear when you are ready')
  expect(eventLog(w)).toContain('"auto-off"')
})

test('a channel prompt in the idle window keeps auto mode disarmed: a nudge, no handover (R2-06)', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await $.session.start(START)
  await $.prompt.submit(human('go'))
  await w.clock.advance(31 * MIN)
  await $.tool.call({ tool: 'Bash', tool_use_id: 'b', command: 'ls' } as never)
  await $.session.measure(measure(20))
  await $.prompt.submit({ text: 'from slack', wait: false, origin: { kind: 'channel' } as never })
  await $.tool.call({ tool: 'Bash', tool_use_id: 'b2', command: 'ls' } as never)
  await $.session.measure(measure(36))
  await w.clock.settle()
  expect(w.submits.some(x => x.text.includes(TOOL))).toBe(false)
  expect(w.state.get('context-vigil-mod.barShown')).toBe(true)   // nudged on the bar instead
})

test('a lost instruction stops blocking after ten idle minutes: /vho starts a fresh one (R2-03)', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.command.run(vho)
  await w.clock.settle()                               // started: true, but no turn.start ever matches
  await $.turn.complete(turn('other'))
  await $.command.run(vho)                             // still inside ten minutes: refused, one instruction
  await w.clock.settle()
  expect(w.submits.filter(x => x.text.includes(TOOL))).toHaveLength(1)
  await w.clock.advance(10 * MIN)
  await $.command.run(vho)
  await w.clock.settle()
  expect(w.submits.filter(x => x.text.includes(TOOL))).toHaveLength(2)
  expect(w.notices.some(n => n.includes('never completed'))).toBe(true)
  expect(eventLog(w)).toContain('"awaiting-expired"')
})

test('an instruction queued behind a long running turn is not declared lost (R2-03)', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.command.run(vho)
  await w.clock.settle()
  for (let i = 0; i < 11; i++) {
    await w.clock.advance(MIN)
    await $.tool.call({ tool: 'Bash', tool_use_id: `b${i}`, command: 'ls' } as never)
  }
  await $.command.run(vho)
  await w.clock.settle()
  expect(w.submits.filter(x => x.text.includes(TOOL))).toHaveLength(1)
  expect(w.notices.some(n => n.includes('already in progress'))).toBe(true)
})

test('the instruction retry never submits while latched: it waits for the latch (R2-09)', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.command.run(vho)
  await w.clock.settle()
  await $.turn.start({ text: w.submits.at(-1)?.text ?? '', turnId: 'a' } as never)
  w.rateLimits.value = [{ kind: 'five_hour', percentUsed: 100, resetsAt: new Date(1_000_000 + 60 * MIN).toISOString() }]
  await $.classic.StopFailure({ error: 'rate_limit' } as never)
  await $.turn.complete(turn('a'))
  await w.clock.settle()
  expect(w.submits.filter(x => x.text.includes(TOOL))).toHaveLength(1)
  expect(w.state.get('context-vigil-mod.awaiting')).toBe(null)
  expect(w.state.get('context-vigil-mod.deferred')).toMatchObject({ reason: 'request' })
  expect(w.notices).toContain('⏳ Handover waiting — the usage limit is in force')
})

test('the instruction retry under stand-down is dropped with a notice (R2-09)', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.command.run(vho)
  await w.clock.settle()
  await $.turn.start({ text: w.submits.at(-1)?.text ?? '', turnId: 'a' } as never)
  w.files.set('/cfg/context-vigil/sessions/s1.json', '')   // the classic hooks claim the session (spec §7)
  await $.session.start(START)                           // a reload re-reads the interlock; $.state keeps `awaiting`
  await $.turn.complete(turn('a'))
  await w.clock.settle()
  expect(w.submits.filter(x => x.text.includes(TOOL))).toHaveLength(1)
  expect(w.state.get('context-vigil-mod.awaiting')).toBe(null)
  expect(w.notices).toContain("📜 Couldn't write a handover — nothing was cleared")
})

test('a store that refuses the pending handover: the hook does not throw, a notice and the result say so (R2-15)', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.command.run(vho)
  await w.clock.settle()
  w.onStoreSet.value = async key => { if (key.startsWith('pending:')) throw new Error('store is full') }
  const r = await $.tool.call(call() as never) as { result?: string }
  expect(r.result).toContain('not saved')
  expect(w.notices).toContain(V.handoverFailed)
  await w.clock.settle()
  expect(w.commands).not.toContain('clear')
})

test('a clear attempt that errors is announced and leaves the handover offered, not stranded (R2-15)', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  await $.command.run(vho)
  await w.clock.settle()
  await $.tool.call(call() as never)
  w.promptReadFails.count = 1
  await w.clock.settle()
  expect(w.notices).toContain(V.clearRejected)
  expect(w.commands).not.toContain('clear')
  expect(w.state.get('context-vigil-mod.pending')).not.toBe(null)
})
