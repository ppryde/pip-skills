import { expect, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { On } from 'claude-code'
import { START, classicStart, turn, USAGE, BAND, bandLines, world } from './world'
import type { World } from './world'

const SEC = 1000
const SETTINGS = '/cfg/settings.json'
const SCRIPT = '/home/u/.claude/line.sh'
const BACKUP = '/cfg/census/census-mod.statusline.json'
const STATUS_LINE = { type: 'command', command: 'bash ~/.claude/line.sh', padding: 0 }
const MARKED = 'input=$(cat)\n# --- census: record status-line payload (managed by `census`; do not edit) ---\nprintf x | census ingest\n# --- end census ---\necho line\n'
const settings = (extra: object = {}) => JSON.stringify({ model: 'opus', statusLine: STATUS_LINE, env: { A: '1' }, ...extra }, null, 2) + '\n'
const saved = (w: World) => w.store.get('census-mod:setup') as Record<string, unknown>
const headers = (w: World) => w.asks.map(a => a.header)
const pick = (w: World, label: string | RegExp) => (q: { options: string[] }) => q.options.find(o => (typeof label === 'string' ? o.startsWith(label) : label.test(o))) ?? null

async function setupRun($: Engine, w: World, args = '') {
  await $.session.start(START)
  await w.clock.advance(0)
  const r = (await $.command.run({ command: 'census-setup', args, origin: { kind: 'composer' } } as never)) as { text?: string }
  for (let i = 0; i < 6; i++) await w.clock.advance(0)
  return r
}
// A world whose status line records into census, as `census install` leaves it.
const doubleWriter = (w: World) => {
  w.files.set(SETTINGS, settings())
  w.files.set(SCRIPT, MARKED)
}

test('/census-setup is a registered command that asks, in order: record, band, layout, PR', async ($, on) => {
  const w = world(on)
  const r = await setupRun($, w)

  expect(r.text).toContain('questions follow')
  expect(headers(w)).toEqual(['📝 Record', '🎛️ Band', '📐 Layout', '🔀 PR'])
  expect(saved(w)).toMatchObject({ record: 'yes', draw: true, preset: 'two', pr: true, offered: true })
  expect(w.toasts.at(-1)).toBe('🧭 census-mod is set up')
  expect(w.logs.join('\n')).toContain('undo any time: /census-setup off')
  expect(w.logs.at(-1)).toBe('📊 /census:vitals shows this session on your phone')
})

test('the exact questions', async ($, on) => {
  const w = world(on)
  await setupRun($, w)

  expect(w.asks).toEqual([
    { header: '📝 Record', question: "Record this account's sessions into the census store?", options: ['Yes — the real census store (Recommended)', 'Shadow — a separate store, to compare first', 'No — do not record'] },
    { header: '🎛️ Band', question: 'Draw the status line in the band above the prompt?', options: ['Yes (Recommended)', 'No'] },
    { header: '📐 Layout', question: 'Which segments in the band? (CENSUS_STATUSLINE_SEGMENTS still overrides this.)', options: ['Your two lines (Recommended)', 'Compact — one line', 'Minimal — context, limits / git'] },
    { header: '🔀 PR', question: "Show the branch's open PR (number, review state) using gh? No means gh is never called.", options: ['Yes (Recommended)', "No — never call gh"] },
  ])
})

test('step 1 asks nothing: it reports the CLI, the status line and any other writer', async ($, on) => {
  const w = world(on)
  doubleWriter(w)
  await setupRun($, w)
  const log = w.logs.join('\n')

  expect(log).toContain('census CLI: /plugins/census/scripts/cli.py')
  expect(log).toContain('status line: bash ~/.claude/line.sh (it records into census)')
  expect(log).toContain('another writer on the store: no')
})

test('another writer is reported when a status line wrote into the store a moment ago', async ($, on) => {
  const w = world(on)
  w.dirs.set('/cfg/census/sessions', ['a.json'])
  w.files.set('/cfg/census/sessions/a.json', JSON.stringify({ updated_at: 1_791_000_000 - 30, payload: {} }))
  await setupRun($, w)

  expect(w.logs.join('\n')).toContain('another writer on the store: yes')
})

// ---- the paths ----------------------------------------------------------------------------------------------

test('Shadow records into <config dir>/census-shadow through the child CENSUS_STORE', async ($, on) => {
  const w = world(on)
  w.answer.value = q => (q.header === '📝 Record' ? pick(w, 'Shadow')(q) : q.options[0] ?? null)
  await setupRun($, w)
  await $.turn.complete(turn(USAGE))
  await w.clock.advance(3 * SEC)

  expect(saved(w)).toMatchObject({ record: 'shadow' })
  expect(w.ingests.at(-1)?.env).toEqual({ CENSUS_STORE: '/cfg/census-shadow' })
})

test('record No with the band on keeps drawing and stops recording', async ($, on) => {
  const w = world(on)
  w.answer.value = q => (q.header === '📝 Record' ? pick(w, 'No')(q) : q.options[0] ?? null)
  await setupRun($, w)
  const before = w.ingests.length
  await $.turn.complete(turn(USAGE))
  await w.clock.advance(5 * SEC)

  expect(w.ingests).toHaveLength(before)
  const ui = await $.ui.mount(BAND())
  expect((await bandLines(ui)).length).toBeGreaterThan(0)
  await ui.unmount()
})

test('record No and band No is "off": no questions after, nothing recorded, nothing drawn', async ($, on) => {
  const w = world(on)
  w.answer.value = q => (q.header === '📝 Record' ? pick(w, 'No')(q) : q.header === '🎛️ Band' ? 'No' : q.options[0] ?? null)
  await setupRun($, w)

  expect(headers(w)).toEqual(['📝 Record', '🎛️ Band'])
  expect(saved(w)).toMatchObject({ record: 'no', draw: false })
  expect(w.toasts.at(-1)).toBe('🧭 census-mod is off')
  const n = w.ingests.length
  await $.turn.complete(turn(USAGE))
  await w.clock.advance(5 * SEC)
  expect(w.ingests).toHaveLength(n)
  const ui = await $.ui.mount(BAND())
  expect(await bandLines(ui)).toEqual([])
  await ui.unmount()
})

test('a layout preset is stored and drawn', async ($, on) => {
  const w = world(on)
  w.answer.value = q => (q.header === '📐 Layout' ? pick(w, 'Minimal')(q) : q.options[0] ?? null)
  await setupRun($, w)
  const ui = await $.ui.mount(BAND())

  expect(await bandLines(ui)).toEqual(['🧠 •ᗧ•••••••• 9%', '🌿 main'])
  await ui.unmount()
})

test('CENSUS_STATUSLINE_SEGMENTS outranks a stored layout', async ($, on) => {
  const w = world(on, { env: { CLAUDE_CONFIG_DIR: '/cfg', HOME: '/home/u', CENSUS_STATUSLINE_SEGMENTS: 'model' } })
  w.store.set('census-mod:setup', { offered: true, preset: 'minimal' })
  await $.session.start(START)
  await w.clock.advance(0)
  const ui = await $.ui.mount(BAND())

  expect(await bandLines(ui)).toEqual(['🦾 Opus 5.5'])
  await ui.unmount()
})

test('PR No means gh is never called, whatever triggers it', async ($, on) => {
  const w = world(on)
  w.answer.value = q => (q.header === '🔀 PR' ? pick(w, 'No')(q) : q.options[0] ?? null)
  await setupRun($, w)
  const before = w.runs.filter(r => r.argv[0] === 'gh').length // asked once at the start, before the answer
  await $.tool.call({ tool: 'Bash', command: 'git push' } as never)
  await $.tool.call({ tool: 'Bash', command: 'gh pr create' } as never)
  await w.clock.advance(10 * 60 * SEC)

  expect(saved(w)).toMatchObject({ pr: false })
  expect(w.runs.filter(r => r.argv[0] === 'gh')).toHaveLength(before)
})

// ---- two writers -----------------------------------------------------------------------------------------------

test('no double-writer question when the status line has no census block', async ($, on) => {
  const w = world(on)
  w.files.set(SETTINGS, settings())
  w.files.set(SCRIPT, 'echo line\n')
  await setupRun($, w)

  expect(headers(w)).not.toContain('⚠️ Writers')
})

test('...nor when recording to a shadow store, which is not the line\'s store', async ($, on) => {
  const w = world(on)
  doubleWriter(w)
  w.answer.value = q => (q.header === '📝 Record' ? pick(w, 'Shadow')(q) : q.options[0] ?? null)
  await setupRun($, w)

  expect(headers(w)).not.toContain('⚠️ Writers')
})

test('the census command itself counts as the ingest block', async ($, on) => {
  const w = world(on)
  w.files.set(SETTINGS, settings({ statusLine: { type: 'command', command: 'census statusline' } }))
  await setupRun($, w)

  expect(headers(w)).toContain('⚠️ Writers')
})

test('the double-writer question', async ($, on) => {
  const w = world(on)
  doubleWriter(w)
  await setupRun($, w)

  expect(w.asks.find(a => a.header === '⚠️ Writers')).toEqual({
    header: '⚠️ Writers',
    question: "This account's status line also records into the census store. Two writers on one store muddle idle and liveness. What now?",
    options: ["Remove this account's status line (the band replaces it) (Recommended)", "Keep my status line; census-mod won't record", 'Keep both (not recommended)'],
  })
})

test('without the band there is nothing to replace the status line: removal is not offered', async ($, on) => {
  const w = world(on)
  doubleWriter(w)
  w.answer.value = q => (q.header === '🎛️ Band' ? 'No' : q.options[0] ?? null)
  await setupRun($, w)

  expect(w.asks.find(a => a.header === '⚠️ Writers')?.options).toEqual(["Keep my status line; census-mod won't record (Recommended)", 'Keep both (not recommended)'])
})

test('Remove: statusLine backed up exactly, settings.json rewritten atomically with every other key, scripts untouched', async ($, on) => {
  const w = world(on)
  doubleWriter(w)
  await setupRun($, w)

  expect(JSON.parse(w.files.get(SETTINGS) ?? '{}')).toEqual({ model: 'opus', env: { A: '1' } })
  expect(JSON.parse(w.files.get(BACKUP) ?? '{}')).toMatchObject({ statusLine: STATUS_LINE, from: SETTINGS })
  expect(w.files.has('/cfg/settings.json.census-mod.tmp')).toBe(false) // renamed over, not left behind
  expect(w.runs.some(r => r.argv[0] === 'mv' && r.argv.at(-1) === SETTINGS)).toBe(true)
  expect(w.files.get(SCRIPT)).toBe(MARKED)
  expect(saved(w)).toMatchObject({ record: 'yes' })
  expect(w.logs.join('\n')).toContain(BACKUP)
})

test('Keep my status line: census-mod will not record, and settings.json is untouched', async ($, on) => {
  const w = world(on)
  doubleWriter(w)
  w.answer.value = q => (q.header === '⚠️ Writers' ? pick(w, 'Keep my')(q) : q.options[0] ?? null)
  await setupRun($, w)

  expect(saved(w)).toMatchObject({ record: 'no' })
  expect(w.files.get(SETTINGS)).toBe(settings())
  expect(w.files.has(BACKUP)).toBe(false)
  const n = w.ingests.length
  await $.turn.complete(turn(USAGE))
  await w.clock.advance(5 * SEC)
  expect(w.ingests).toHaveLength(n)
})

test('Keep both: allowed, recorded as asked, nothing touched', async ($, on) => {
  const w = world(on)
  doubleWriter(w)
  w.answer.value = q => (q.header === '⚠️ Writers' ? pick(w, 'Keep both')(q) : q.options[0] ?? null)
  await setupRun($, w)

  expect(saved(w)).toMatchObject({ record: 'yes' })
  expect(w.files.get(SETTINGS)).toBe(settings())
})

test('settings.json that is not valid JSON is never edited: the status line stays, recording stops', async ($, on) => {
  const w = world(on)
  doubleWriter(w)
  w.answer.value = q => {
    if (q.header === '⚠️ Writers') w.files.set(SETTINGS, '{ "statusLine": ') // it went bad after it was read
    return q.options[0] ?? null
  }
  await setupRun($, w)

  expect(w.files.get(SETTINGS)).toBe('{ "statusLine": ')
  expect(w.files.has(BACKUP)).toBe(false)
  expect(saved(w)).toMatchObject({ record: 'no' })
  expect(w.logs.join('\n')).toContain('is not valid JSON, so I left your status line alone')
})

// ---- off ------------------------------------------------------------------------------------------------------------

test('/census-setup off restores a removed status line exactly, then stops recording and drawing', async ($, on) => {
  const w = world(on)
  doubleWriter(w)
  await setupRun($, w)
  const r = await setupRun($, w, 'off')

  expect(r.text).toContain('census-mod is off')
  expect(JSON.parse(w.files.get(SETTINGS) ?? '{}')).toEqual({ model: 'opus', statusLine: STATUS_LINE, env: { A: '1' } })
  expect(w.files.has(BACKUP)).toBe(false)
  expect(saved(w)).toMatchObject({ record: 'no', draw: false })
  expect(w.logs.join('\n')).toContain('your status line is back in /cfg/settings.json')
})

test('off leaves a different status line alone and keeps the backup, and says so', async ($, on) => {
  const w = world(on)
  doubleWriter(w)
  await setupRun($, w)
  w.files.set(SETTINGS, JSON.stringify({ model: 'opus', statusLine: { type: 'command', command: 'mine.sh' } }))
  await setupRun($, w, 'off')

  expect(JSON.parse(w.files.get(SETTINGS) ?? '{}').statusLine.command).toBe('mine.sh')
  expect(w.files.has(BACKUP)).toBe(true)
  expect(w.logs.join('\n')).toContain('it has a different status line now')
})

test('off with nothing to restore just stops', async ($, on) => {
  const w = world(on)
  const r = await setupRun($, w, 'off')

  expect(r.text).toContain('off')
  expect(w.files.has(BACKUP)).toBe(false)
  expect(saved(w)).toMatchObject({ record: 'no', draw: false })
})

test('an unknown argument says how to use it', async ($, on) => {
  const w = world(on)
  expect((await setupRun($, w, 'nope')).text).toBe('Usage: /census-setup (guided setup) or /census-setup off')
  expect(w.asks).toHaveLength(0)
})

// ---- defaults and precedence ------------------------------------------------------------------------------------------

test('before any answer: records to the real store when the status line does not record', async ($, on) => {
  const w = world(on)
  w.store.delete('census-mod:setup')
  await $.session.start(START)
  await w.clock.advance(0)

  expect(w.ingests).toHaveLength(1)
  const ui = await $.ui.mount(BAND())
  expect((await bandLines(ui)).length).toBeGreaterThan(0)
  await ui.unmount()
})

test('before any answer: records nothing while the status line records into census', async ($, on) => {
  const w = world(on)
  doubleWriter(w)
  await $.session.start(START)
  await w.clock.advance(0)
  await $.turn.complete(turn(USAGE))
  await w.clock.advance(5 * SEC)

  expect(w.ingests).toHaveLength(0)
  const ui = await $.ui.mount(BAND())
  expect((await bandLines(ui)).length).toBeGreaterThan(0) // the band is still drawn (Draw defaults to yes)
  await ui.unmount()
})

test('CENSUS_MOD_STORE outranks an answer of No', async ($, on) => {
  const w = world(on, { env: { CLAUDE_CONFIG_DIR: '/cfg', HOME: '/home/u', CENSUS_MOD_STORE: '/cfg/census-x' } })
  w.store.set('census-mod:setup', { offered: true, record: 'no' })
  await $.session.start(START)
  await w.clock.advance(0)

  expect(w.ingests.at(-1)?.env).toEqual({ CENSUS_STORE: '/cfg/census-x' })
})

// ---- census too old or missing ----------------------------------------------------------------------------------------

test('census older than 0.5.0 is said so and recording is offered off', async ($, on) => {
  const w = world(on, { files: { '/plugins/census/.claude-plugin/plugin.json': JSON.stringify({ version: '0.4.0' }) } })
  await setupRun($, w)

  expect(w.asks[0]).toEqual({
    header: '📝 Census',
    question: 'The census plugin here is 0.4.0; census-mod needs 0.5.0 or newer to tell a live session from a gone one. Record anyway?',
    options: ["Don't record (Recommended)", 'Record anyway'],
  })
  expect(headers(w)).not.toContain('📝 Record')
  expect(saved(w)).toMatchObject({ record: 'no' })
})

test('...and Record anyway carries on to the record question', async ($, on) => {
  const w = world(on, { files: { '/plugins/census/.claude-plugin/plugin.json': JSON.stringify({ version: '0.4.0' }) } })
  w.answer.value = q => (q.header === '📝 Census' ? 'Record anyway' : q.options[0] ?? null)
  await setupRun($, w)

  expect(headers(w)).toContain('📝 Record')
})

test('no census at all: says so and does not ask about recording', async ($, on) => {
  const w = world(on)
  w.files.delete('/cfg/census/cli.path')
  await setupRun($, w)

  expect(headers(w)).not.toContain('📝 Record')
  expect(w.logs.join('\n')).toContain('census not found')
})

// ---- the one-time offer ----------------------------------------------------------------------------------------------------

test('the first session after install is offered setup, once', async ($, on) => {
  const w = world(on)
  w.store.delete('census-mod:setup')
  await $.session.start(START)
  await w.clock.advance(0)
  expect(w.asks).toHaveLength(0) // not at once: the start settles first
  await w.clock.advance(3 * SEC)
  for (let i = 0; i < 6; i++) await w.clock.advance(0)

  expect(w.asks[0]).toEqual({
    header: '🧭 Setup',
    question: 'census-mod is installed. Set it up now? It takes a few questions: whether to record sessions into census, whether to draw the status-line band, and which layout.',
    options: ['Set it up now (Recommended)', 'Not now — use the defaults'],
  })
  expect(headers(w)).toEqual(['🧭 Setup', '📝 Record', '🎛️ Band', '📐 Layout', '🔀 PR'])
  expect(saved(w).offered).toBe(true)
})

async function declinesOffer($: Engine, on: On, reply: string | null) {
  const w = world(on)
  w.store.delete('census-mod:setup')
  w.answer.value = () => reply
  await $.session.start(START)
  await w.clock.advance(3 * SEC)
  for (let i = 0; i < 6; i++) await w.clock.advance(0)

  expect(w.asks).toHaveLength(1)
  expect(saved(w)).toEqual({ offered: true }) // nothing new recorded: the defaults stand
  await w.clock.advance(10 * SEC)
  expect(w.asks).toHaveLength(1)
  expect(w.ingests.length).toBeGreaterThan(0) // default: records to the real store
}

test('Not now keeps the defaults and is never offered again', async ($, on) => {
  await declinesOffer($, on, 'Not now — use the defaults')
})

test('a dismissed offer does too', async ($, on) => {
  await declinesOffer($, on, null)
})

test('an already-offered install is not offered', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await w.clock.advance(10 * SEC)

  expect(w.asks).toHaveLength(0)
})

// ---- the person leaves, or is on the phone ---------------------------------------------------------------------------------------

test('a dismissed dialog stops setup, says so, and keeps what was answered', async ($, on) => {
  const w = world(on)
  w.answer.value = q => (q.header === '📐 Layout' ? null : q.options[0] ?? null)
  await setupRun($, w)

  expect(saved(w)).toMatchObject({ record: 'yes', draw: true })
  expect(saved(w).preset).toBeUndefined()
  expect(headers(w)).not.toContain('🔀 PR')
  expect(w.toasts.at(-1)).toContain('census-setup stopped')
})

test('a /clear while a dialog is open drops that setup: its late answer is not applied', async ($, on) => {
  const w = world(on)
  let release: () => void = () => undefined
  w.askGate.value = new Promise<void>(res => { release = res })
  await $.session.start(START)
  await w.clock.advance(0)
  await $.command.run({ command: 'census-setup', args: '', origin: { kind: 'composer' } } as never)
  await w.clock.advance(0)
  w.sessionId.value = 's2'
  await $.classic.SessionStart(classicStart('clear', 's2'))
  release()
  for (let i = 0; i < 6; i++) await w.clock.advance(0)

  expect(w.asks).toHaveLength(1)
  expect(saved(w).record).toBeUndefined()
})

test('setup talks only through $.ui.ask: nothing is submitted to the model', async ($, on) => {
  const w = world(on) // the world has no prompt.submit op at all: a submit would throw
  const r = await setupRun($, w)

  expect(r.text).toBeDefined()
  expect(w.asks.length).toBeGreaterThan(0)
  expect(w.runs.some(x => x.argv.includes('submit'))).toBe(false)
})
