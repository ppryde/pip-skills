import { expect, test } from 'claude-code/testing'
import { NAME } from '../../plugins/context-vigil-mod/core/name'
import { START, human, turn, world } from './world'
import { V } from '../../plugins/context-vigil-mod/core/voice'

const MIN = 60_000

test('session start registers commands and the tool, resolves the config dir', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  expect(w.registered.commands.sort()).toEqual(['vhandoff', 'vho', 'vsetup'])
  expect(w.registered.tools).toEqual(['vigil_handover'])
})

test('arm and disarm are logged to a per-session day file when auto mode is on', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await $.session.start(START)
  await $.prompt.submit(human('go'))
  await w.clock.advance(31 * MIN)
  await $.turn.complete(turn())
  const day = [...w.files.keys()].find(k => k.startsWith('/cfg/context-vigil-mod/events/'))
  expect(day).toMatch(/\/events\/\d{4}-\d{2}-\d{2}\/s1\.jsonl$/)
  expect(w.files.get(day ?? '')).toContain('"kind":"arm"')
  await $.prompt.submit(human('back'))
  expect(w.files.get(day ?? '')).toContain('"kind":"disarm"')
})

test('auto mode off: the mode still moves to auto, but no arm line is logged', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.prompt.submit(human('go'))
  await w.clock.advance(31 * MIN)
  await $.turn.complete(turn())
  expect(w.state.get('context-vigil-mod.mode')).toBe('auto')
  const text = [...w.files.values()].join('')
  expect(text).not.toContain('"kind":"arm"')
})

test('a draft sitting in the terminal box counts as you being here', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await $.session.start(START)
  await $.prompt.submit(human('go'))
  await w.clock.advance(31 * MIN)
  w.draft.value = 'half a thought'
  await $.turn.complete(turn())
  expect(w.state.get('context-vigil-mod.mode')).toBe('attended')
  w.draft.value = ''
  await w.clock.advance(31 * MIN)
  await $.turn.complete(turn('2'))
  expect(w.state.get('context-vigil-mod.mode')).toBe('auto')
})

test('git refresh: tool calls schedule one coalesced refresh of two commands, off a timer', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await w.clock.advance(1500)          // let the session-start refresh run first
  w.runs.count = 0
  await $.tool.call({ tool: 'Edit', tool_use_id: 'u1', file_path: '/repo/a.ts', old_string: 'a', new_string: 'b' } as never)
  await $.tool.call({ tool: 'Bash', tool_use_id: 'u2', command: 'ls' } as never)
  expect(w.runs.count).toBe(0)
  await w.clock.advance(1500)
  expect(w.runs.count).toBe(2)
  await $.tool.call({ tool: 'Read', tool_use_id: 'u3', file_path: '/repo/a.ts' } as never)
  await w.clock.advance(1500)
  expect(w.runs.count).toBe(2)
})

test('classic installed: stands down with one notice; the state literal is NAME', async ($, on) => {
  const w = world(on, { files: { '/cfg/settings.json': JSON.stringify({ hooks: { Stop: [{ hooks: [{ type: 'command', command: '"/s/context-vigil/scripts/context-vigil" hook stop' }] }] } }) } })
  await $.session.start(START)
  expect(w.notices.filter(n => n.includes('standing down')).length).toBe(1)
  await $.prompt.submit(human('hi'))
  expect(w.state.get(`${NAME}.mode`)).toBe('attended')
  await $.session.measure({ context: { window: 1_000_000, percent: 40 }, rateLimits: [], changed: ['context'] as never })
  expect(w.notices.some(n => n.includes('Context at'))).toBe(false)   // stood down: no nudge
})

test('standing down survives a clear: no second notice, still no nudge', async ($, on) => {
  const w = world(on, { store: { settings: { bar: false } }, files: { '/cfg/settings.json': JSON.stringify({ hooks: { Stop: [{ hooks: [{ type: 'command', command: '"/s/context-vigil/scripts/context-vigil" hook stop' }] }] } }) } })
  await $.session.start(START)
  w.sessionId.value = 's2'
  await $.classic.SessionStart({ source: 'clear' } as never)
  await $.session.measure({ context: { window: 1_000_000, percent: 40 }, rateLimits: [], changed: ['context'] as never })
  expect(w.notices.filter(n => n.includes('standing down')).length).toBe(1)
  expect(w.notices.some(n => n.includes('Context at'))).toBe(false)
})

test('a fresh session start resets module caches: a stale git timer neither blocks nor doubles the refresh', async ($, on) => {
  const w = world(on)
  await $.session.start(START)          // schedules a refresh at +1500
  w.sessionId.value = 's9'
  await $.session.start(START)          // bindSession cancels it and schedules its own
  await w.clock.advance(1500)
  expect(w.runs.count).toBe(2)
})

test('classic.SessionStart returns watch paths for .git', async ($, on) => {
  world(on)
  await $.session.start(START)
  const r = await $.classic.SessionStart({ source: 'startup' } as never)
  expect(r.watchPaths).toEqual(['/repo/.git/HEAD', '/repo/.git/index'])
})

test('a human prompt racing an agent step is not erased: lastHumanAt survives and the mode ends attended', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await $.session.start(START)
  await $.prompt.submit(human('go'))
  await w.clock.advance(31 * MIN)
  await Promise.all([$.turn.complete(turn()), $.prompt.submit(human('here I am'))])
  expect(w.state.get('context-vigil-mod.mode')).toBe('attended')   // 'go' is 31 min old: only 'here I am' can make it attended
  // The agent step may land first and arm; the human then disarms it. What must never happen is arm without that disarm.
  const lines = [...w.files.values()].join('').split('\n').filter(Boolean).map(l => JSON.parse(l).kind as string)
  expect(lines.filter(k => k === 'arm').length).toBe(lines.filter(k => k === 'disarm').length)
})

test('a refused toast is not an unhandled rejection: the log line still goes out', async ($, on) => {
  const w = world(on, { files: { '/cfg/settings.json': JSON.stringify({ hooks: { Stop: [{ hooks: [{ type: 'command', command: '"/s/context-vigil/scripts/context-vigil" hook stop' }] }] } }) } })
  w.toastRefused.value = true
  await $.session.start(START)
  expect(w.logs.filter(n => n.includes('standing down')).length).toBe(1)
})

// R1-15: the first write of a day is a read-then-append; two hooks racing it must keep both lines.
test('two events racing the first log of a day both land in the file', async ($, on) => {
  const w = world(on, { store: { settings: { auto: true } } })
  await $.session.start(START)
  await $.prompt.submit(human('go'))
  await w.clock.advance(31 * MIN)
  let open = () => {}
  w.fsRead.gate = new Promise<void>(r => { open = r })
  const arm = $.turn.complete(turn())
  const disarm = $.prompt.submit(human('back'))
  await w.clock.advance(1)
  open()
  await Promise.all([arm, disarm])
  const day = [...w.files.keys()].find(k => k.startsWith('/cfg/context-vigil-mod/events/')) ?? ''
  const kinds = (w.files.get(day) ?? '').trim().split('\n').map(l => (JSON.parse(l) as { kind: string }).kind)
  expect(kinds).toContain('arm')
  expect(kinds).toContain('disarm')
})

test('an unreadable day file is left alone, never truncated', async ($, on) => {
  const day = '/cfg/context-vigil-mod/events/1970-01-01/s1.jsonl'
  const w = world(on, { store: { settings: { auto: true } }, now: 1_000_000, files: { [day]: '{"kept":true}\n' } })
  await $.session.start(START)
  w.fsRead.error = 'EIO read failed'
  await $.prompt.submit(human('go'))
  await w.clock.advance(31 * MIN)
  await $.turn.complete(turn())
  expect(w.files.get(day)).toBe('{"kept":true}\n')
})

test('R1-13: a /compact starts the nudge ladder over', async ($, on) => {
  const w = world(on, { store: { settings: { bar: false } } })
  await $.session.start(START)
  await $.prompt.submit(human('hi'))
  const m = (percent: number) => ({ context: { window: 1_000_000, percent }, rateLimits: [], changed: ['context'] as never })
  await $.session.measure(m(45))
  expect(w.notices.filter(n => n.includes('Context at 45%'))).toHaveLength(1)
  await $.classic.SessionStart({ source: 'compact' } as never)
  await $.session.measure(m(36))
  expect(w.notices.filter(n => n.includes('Context at 36%'))).toHaveLength(1)
})

test('R1-17: parked handovers older than two weeks are pruned at session start; fresh ones stay', async ($, on) => {
  const DAY = 86_400_000
  const old = { session: 'old', path: '/p', name: 'n', reason: 'request', markdown: '# x', resume: true, followUp: null, createdAt: 1_000_000 - 30 * DAY }
  const fresh = { ...old, session: 'other', createdAt: 1_000_000 - DAY }
  const w = world(on, { now: 1_000_000, store: { 'pending:old': old, 'pending:other': fresh, settings: {} } })
  await $.session.start(START)
  expect(w.store.has('pending:old')).toBe(false)
  expect(w.store.has('pending:other')).toBe(true)
  expect(w.store.has('settings')).toBe(true)
})

const CLASSIC = { '/cfg/settings.json': JSON.stringify({ hooks: { Stop: [{ hooks: [{ type: 'command', command: '"/s/context-vigil/scripts/context-vigil" hook stop' }] }] } }) }
const vhoCmd = { command: 'vho', args: '', origin: { kind: 'composer' } as never } as never

test('/vho under stand-down says classic is in charge, not "Handing over" (R2-14)', async ($, on) => {
  const w = world(on, { files: CLASSIC })
  await $.session.start(START)
  const r = await $.command.run(vhoCmd) as { text?: string }
  expect(r.text).toBe(V.classicActive)
  expect(w.submits).toHaveLength(0)
})

test('/vho while a handover is in flight says so, not "Handing over" (R2-14)', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await $.command.run(vhoCmd)
  await w.clock.settle()
  const r = await $.command.run(vhoCmd) as { text?: string }
  expect(r.text).toBe(V.handoverInProgress)
})

test('/vho while the limit latch is set says it is waiting (R2-14)', async ($, on) => {
  const w = world(on, { store: { latch: { kind: 'five_hour', resetsAtMs: 1_000_000 + 3_600_000 } } })
  await $.session.start(START)
  const r = await $.command.run(vhoCmd) as { text?: string }
  expect(r.text).toBe(V.waiting('latched'))
})
