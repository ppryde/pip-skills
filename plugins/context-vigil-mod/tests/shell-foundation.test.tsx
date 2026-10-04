import { expect, test } from 'claude-code/testing'
import { NAME } from '../core/name'
import { START, human, turn, world } from './world'

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
  expect(w.state.get(`${NAME}.standDown`)).toBe(true)
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
  const humanAt = w.clock.now()
  await Promise.all([$.turn.complete(turn()), $.prompt.submit(human('here I am'))])
  expect((w.state.get('context-vigil-mod.activity') as { lastHumanAt: number }).lastHumanAt).toBe(humanAt)
  expect(w.state.get('context-vigil-mod.mode')).toBe('attended')
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
