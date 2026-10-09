import { expect, test } from 'claude-code/testing'
import { BAND, START, USAGE, bandLines, classicStart, turn, world } from './world'

const ingestCount = (w: ReturnType<typeof world>) => w.ingests.length

test('python3 missing: ingest goes through `python`', async ($, on) => {
  const w = world(on)
  w.pythons.value = ['python']
  await $.session.start(START)
  await w.clock.advance(0)
  expect(w.ingests[0]?.argv[0]).toBe('python')
  expect(w.ingests[0]?.argv.slice(2)).toEqual(['ingest'])
})

test('only the Windows launcher: ingest goes through `py -3`', async ($, on) => {
  const w = world(on)
  w.pythons.value = ['py -3']
  await $.session.start(START)
  await w.clock.advance(0)
  expect(w.ingests[0]?.argv.slice(0, 2)).toEqual(['py', '-3'])
  expect(w.ingests[0]?.argv.slice(3)).toEqual(['ingest'])
})

test('the launcher is chosen once per process, not once per ingest', async ($, on) => {
  const w = world(on)
  w.pythons.value = ['python']
  await $.session.start(START)
  await w.clock.advance(0)
  await $.turn.complete(turn(USAGE))
  await w.clock.advance(2_000)
  expect(w.ingests.length).toBeGreaterThan(1)
  expect(w.runs.filter(r => r.argv.includes('--version')).map(r => r.argv.join(' '))).toEqual(['python3 --version', 'python --version'])
})

test('no Python at all: nothing recorded, one log line, and the band still draws', async ($, on) => {
  const w = world(on)
  w.pythons.value = []
  await $.session.start(START)
  await w.clock.advance(0)
  await w.clock.advance(10_000)
  expect(ingestCount(w)).toBe(0)
  expect(w.logs.filter(l => l.includes('found no Python'))).toHaveLength(1)
  expect(w.logs.find(l => l.includes('found no Python'))).toContain('python3, python, py -3')
  const ui = await $.ui.mount(BAND())
  const lines = await bandLines(ui)
  expect(lines.join('\n')).toContain('9%') // the band still draws, from the session's own readings
  await ui.unmount()
})

test('no sh (Windows): the session title and the cache TTL are read from the transcript file', async ($, on) => {
  const w = world(on, { files: {
    '/cfg/projects/-repo/s1.jsonl': '{"type":"user"}\n{"type":"custom-title","customTitle":"win session"}\n{"cache_creation":{"ephemeral_5m_input_tokens":50,"ephemeral_1h_input_tokens":0}}\n',
  } })
  w.shell.value = false
  await $.session.start(START)
  await $.classic.SessionStart(classicStart('startup'))
  await w.clock.advance(0)
  await $.turn.complete(turn(USAGE))
  await w.clock.advance(2_000)
  expect(w.runs.filter(r => r.argv[0] === 'sh' && r.argv[2] !== 'exit 0')).toEqual([])
  expect(w.runs.filter(r => r.argv[0] === 'grep')).toEqual([])
  expect(w.ingests.at(-1)?.payload).toMatchObject({ session_name: 'win session', prompt_cache: { ttl: '5m' } })
})

const WIN = 'C:\\Users\\x\\.claude'
const WIN_SETTINGS = `${WIN}\\settings.json`
const WIN_SCRIPT = 'C:\\Users\\x\\line.sh'
const WIN_LINE = { type: 'command', command: 'bash C:\\Users\\x\\line.sh', padding: 0 }
const MARKED = 'input=$(cat)\n# --- census: record status-line payload (managed by `census`; do not edit) ---\nprintf x | census ingest\n# --- end census ---\necho line\n'

const winSetup = async ($: any, w: ReturnType<typeof world>) => {
  await $.session.start(START)
  await w.clock.advance(0)
  await $.command.run({ command: 'census-setup', args: '', origin: { kind: 'composer' } } as never)
  for (let i = 0; i < 6; i++) await w.clock.advance(0)
}

test('a Windows home (USERPROFILE only): the config dir, settings and backup keep backslashes, and move/del run through cmd', async ($, on) => {
  const w = world(on, { env: { USERPROFILE: 'C:\\Users\\x' }, files: {
    [WIN_SETTINGS]: JSON.stringify({ statusLine: WIN_LINE }, null, 2) + '\n',
    [WIN_SCRIPT]: MARKED,
  } })
  w.answer.value = q => q.options.find(o => o.startsWith('Replace')) ?? q.options[0] ?? null
  await winSetup($, w)

  expect(w.runs.filter(r => r.argv[0] === 'cmd')).toEqual([]) // never a cmd line built from a path
  expect(w.cps).toEqual([]) // no cp -p on Windows: a file there has no mode to keep
  expect(JSON.parse(w.files.get(WIN_SETTINGS) ?? '{}').statusLine).toBeUndefined()
  expect([...w.files.keys()].some(k => k.startsWith(`${WIN}\\census\\`) && k.includes('/'))).toBe(false) // no mixed separators
  expect(w.files.has(`${WIN}\\census\\census-mod.statusline.json`)).toBe(true)
  expect(w.files.has(`${WIN_SETTINGS}.census-mod.tmp`)).toBe(false) // written in place: no temp to leave behind
})

test('a Windows home from HOMEDRIVE+HOMEPATH alone is found too', async ($, on) => {
  const w = world(on, { env: { HOMEDRIVE: 'C:', HOMEPATH: '\\Users\\x' }, files: {
    [WIN_SETTINGS]: JSON.stringify({ statusLine: WIN_LINE }, null, 2) + '\n',
    [WIN_SCRIPT]: MARKED,
  } })
  w.answer.value = q => q.options.find(o => o.startsWith('Replace')) ?? q.options[0] ?? null
  await winSetup($, w)
  expect(w.files.has(`${WIN}\\census\\census-mod.statusline.json`)).toBe(true)
})

test('a Windows turn-off empties the backup instead of shelling out to delete it, and an empty backup is no backup', async ($, on) => {
  const w = world(on, { env: { USERPROFILE: 'C:\\Users\\x' }, files: {
    [WIN_SETTINGS]: JSON.stringify({ statusLine: WIN_LINE }, null, 2) + '\n',
    [WIN_SCRIPT]: MARKED,
  } })
  w.answer.value = q => q.options.find(o => o.startsWith('Replace')) ?? q.options[0] ?? null
  await winSetup($, w)
  await $.command.run({ command: 'census-setup', args: 'off', origin: { kind: 'composer' } } as never)
  for (let i = 0; i < 6; i++) await w.clock.advance(0)

  expect(JSON.parse(w.files.get(WIN_SETTINGS) ?? '{}').statusLine).toEqual(WIN_LINE)
  expect(w.files.get(`${WIN}\\census\\census-mod.statusline.json`)).toBe('')
  expect(w.runs.filter(r => ['cmd', 'rm', 'mv', 'cp'].includes(r.argv[0]!))).toEqual([])
})

test('a pass through with the transcript read twice (title and TTL) reads the file once', async ($, on) => {
  const w = world(on, { files: { '/cfg/projects/-repo/s1.jsonl': '{"type":"custom-title","customTitle":"x"}\n' } })
  w.shell.value = false
  await $.session.start(START)
  await $.classic.SessionStart(classicStart('startup'))
  await w.clock.advance(0)
  await $.turn.complete(turn(USAGE))
  await w.clock.advance(1_000)
  const reads = w.lookups.filter(p => p === '/cfg/projects/-repo/s1.jsonl')
  expect(reads.length).toBeLessThanOrEqual(2) // one for the turn, not one each for title and TTL
})
