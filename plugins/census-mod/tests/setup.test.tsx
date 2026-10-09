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

test('/census-setup is a registered command that asks, in order: record, draw (and where), layout, PR', async ($, on) => {
  const w = world(on, { files: { '/plugins/census/scripts/vitals.py': '' } })
  const r = await setupRun($, w)

  expect(r.text).toContain('questions follow')
  expect(headers(w)).toEqual(['📝 Record', '🎛️ Draw', '📐 Layout', '🔀 PR'])
  expect(saved(w)).toMatchObject({ record: 'yes', draw: true, placement: 'below', preset: 'two', pr: true, offered: true })
  expect(w.toasts.at(-1)).toBe('🧭 census-mod is set up')
  expect(w.logs.join('\n')).toContain('undo any time: /census-setup off')
  expect(w.logs.at(-1)).toBe('📊 /census:vitals shows this session on your phone')
})

test('the exact questions', async ($, on) => {
  const w = world(on)
  await setupRun($, w)

  expect(w.asks).toEqual([
    { header: '📝 Record', question: "Record this account's sessions into census? That's what the overseer dashboard, /census:vitals and session liveness read (context, cost, limits, git, PR) — without it they see nothing from this account.", options: ['Yes — record into census (dashboards, vitals and liveness use it) (Recommended)', "No — don't record (dashboards and vitals won't see this account)"] },
    { header: '🎛️ Draw', question: 'Should census-mod draw your status line, and where?', options: ["Yes — below the input, under Claude Code's hint line (Recommended)", 'Yes — above the input, in the band', 'No — record only, draw nothing'] },
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

test('Shadow records into <config dir>/census-shadow through the child CENSUS_STORE, and the summary says what that means', async ($, on) => {
  const w = world(on)
  doubleWriter(w) // Shadow is only offered where something already records into census
  w.answer.value = q => (q.header === '📝 Record' ? pick(w, 'Shadow')(q) : q.options[0] ?? null)
  await setupRun($, w)
  await $.turn.complete(turn(USAGE))
  await w.clock.advance(3 * SEC)

  expect(saved(w)).toMatchObject({ record: 'shadow' })
  expect(w.ingests.at(-1)?.env).toEqual({ CENSUS_STORE: '/cfg/census-shadow' })
  expect(w.logs.join('\n')).toContain("recording: shadow store /cfg/census-shadow — the dashboards and vitals do not read it; run /census-setup and answer Yes to record into census itself")
})

test('record No with the band on keeps drawing and stops recording', async ($, on) => {
  const w = world(on)
  w.answer.value = q => (q.header === '📝 Record' ? pick(w, 'No')(q) : q.header === '🎛️ Draw' ? pick(w, 'Yes — above')(q) : q.options[0] ?? null)
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
  w.answer.value = q => (q.header === '📝 Record' ? pick(w, 'No')(q) : q.header === '🎛️ Draw' ? 'No — record only, draw nothing' : q.options[0] ?? null)
  await setupRun($, w)

  expect(headers(w)).toEqual(['📝 Record', '🎛️ Draw'])
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
  w.answer.value = q => (q.header === '📐 Layout' ? pick(w, 'Minimal')(q) : q.header === '🎛️ Draw' ? pick(w, 'Yes — above')(q) : q.options[0] ?? null)
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

  expect(await bandLines(ui)).toEqual(['✻  Opus 5.5'])
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
  w.answer.value = q => (q.header === '📝 Record' ? pick(w, 'Yes — record into census')(q) : q.options[0] ?? null)
  await setupRun($, w)

  expect(headers(w)).toContain('⚠️ Writers')
})

test('the double-writer question', async ($, on) => {
  const w = world(on)
  doubleWriter(w)
  w.answer.value = q => (q.header === '📝 Record' ? pick(w, 'Yes — record into census')(q) : q.options[0] ?? null)
  await setupRun($, w)

  expect(w.asks.find(a => a.header === '⚠️ Writers')).toEqual({
    header: '⚠️ Writers',
    question: "This account's status line also records into the census store. Two writers on one store muddle idle and liveness. What now?",
    options: ["Remove this account's status line (census-mod draws it instead) (Recommended)", "Keep my status line; census-mod won't record", 'Keep both (not recommended)'],
  })
})

test('without the band there is nothing to replace the status line: removal is not offered', async ($, on) => {
  const w = world(on)
  doubleWriter(w)
  w.answer.value = q => (q.header === '🎛️ Draw' ? 'No — record only, draw nothing' : q.options[0] ?? null)
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
  w.answer.value = q => (q.header === '⚠️ Writers' ? pick(w, 'Keep my')(q) : q.header === '📝 Record' ? pick(w, 'Yes — record into census')(q) : q.options[0] ?? null)
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
  w.answer.value = q => (q.header === '⚠️ Writers' ? pick(w, 'Keep both')(q) : q.header === '📝 Record' ? pick(w, 'Yes — record into census')(q) : q.options[0] ?? null)
  await setupRun($, w)

  expect(saved(w)).toMatchObject({ record: 'yes' })
  expect(w.files.get(SETTINGS)).toBe(settings())
})

test('settings.json that is not valid JSON is never edited: the status line stays, recording stops', async ($, on) => {
  const w = world(on)
  doubleWriter(w)
  w.answer.value = q => {
    if (q.header === '⚠️ Writers') w.files.set(SETTINGS, '{ "statusLine": ') // it went bad after it was read
    if (q.header === '📝 Record') return pick(w, 'Yes — record into census')(q)
    return q.options[0] ?? null
  }
  await setupRun($, w)

  expect(w.files.get(SETTINGS)).toBe('{ "statusLine": ')
  expect(w.files.has(BACKUP)).toBe(false)
  expect(saved(w)).toMatchObject({ record: 'no' })
  expect(w.logs.join('\n')).toContain('is not valid JSON, so I left your status line alone')
})

test('Replace (the recommended answer when the status line feeds census): asks only where, then removes it with no writers question', async ($, on) => {
  const w = world(on)
  doubleWriter(w)
  await setupRun($, w)

  const record = w.asks.find(a => a.header === '📝 Record')
  expect(record?.options[0]).toBe('Replace my status line — census-mod records and draws it (Recommended)')
  expect(w.asks.find(a => a.header === '🎛️ Draw')?.options).toEqual(["Yes — below the input, under Claude Code's hint line (Recommended)", 'Yes — above the input, in the band'])
  expect(headers(w)).not.toContain('⚠️ Writers')
  expect(saved(w)).toMatchObject({ record: 'yes', draw: true, placement: 'below' })
  expect(w.files.has(BACKUP)).toBe(true)
  expect(JSON.parse(w.files.get(SETTINGS) ?? '{}')).not.toHaveProperty('statusLine')
})

test('with CENSUS_MOD_STORE in effect (records to a shadow store) the status line is never removed: the real store still needs it', async ($, on) => {
  const w = world(on, { env: { CLAUDE_CONFIG_DIR: '/cfg', HOME: '/home/u', CENSUS_MOD_STORE: '/cfg/census-x' } })
  doubleWriter(w)
  await setupRun($, w) // the first answers: Replace, then draw below

  expect(w.files.get(SETTINGS)).toBe(settings())
  expect(w.files.has(BACKUP)).toBe(false)
  expect(w.files.get(SCRIPT)).toBe(MARKED)
  expect(headers(w)).not.toContain('⚠️ Writers')
  expect(w.logs.join('\n')).toContain('your status line was kept: CENSUS_MOD_STORE makes census-mod record to a shadow store')
  expect(w.logs.join('\n')).toContain('recording: shadow store /cfg/census-x')
})

test('a status line that does not feed census is never offered for replacement and never touched', async ($, on) => {
  const w = world(on)
  const own = settings({ statusLine: { type: 'command', command: 'bash ~/my-own-line.sh' } })
  w.files.set(SETTINGS, own)
  await setupRun($, w)

  expect(w.asks.find(a => a.header === '📝 Record')?.options.join('|')).not.toContain('Replace')
  expect(headers(w)).not.toContain('⚠️ Writers')
  expect(w.files.get(SETTINGS)).toBe(own)
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
    question: 'census-mod is installed. Set it up now? It takes a few questions: whether to record sessions into census, whether and where to draw the status line, and which layout.',
    options: ['Set it up now (Recommended)', 'Not now — use the defaults'],
  })
  expect(headers(w)).toEqual(['🧭 Setup', '📝 Record', '🎛️ Draw', '📐 Layout', '🔀 PR'])
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

// ---- writing settings.json safely ------------------------------------------------------------------------------------------

test('a settings.json that is a symlink is written through: the temp file sits beside the TARGET and the link stays', async ($, on) => {
  const w = world(on)
  w.files.set('/dotfiles/settings.json', settings())
  w.links.set(SETTINGS, '/dotfiles/settings.json')
  w.files.set(SCRIPT, MARKED)
  await setupRun($, w)

  expect(w.links.get(SETTINGS)).toBe('/dotfiles/settings.json') // never replaced by a regular file
  expect(JSON.parse(w.files.get('/dotfiles/settings.json') ?? '{}')).toEqual({ model: 'opus', env: { A: '1' } })
  expect(w.runs.some(r => r.argv[0] === 'mv' && r.argv.at(-1) === '/dotfiles/settings.json' && r.argv.at(-2) === '/dotfiles/settings.json.census-mod.tmp')).toBe(true)
})

test('the original file mode is kept: the temp file starts as a copy that preserves it', async ($, on) => {
  const w = world(on)
  doubleWriter(w)
  await setupRun($, w)

  expect(w.cps).toContainEqual(['cp', '-p', SETTINGS, `${SETTINGS}.census-mod.tmp`])
})

test('a failed rename leaves no temp file behind, and the status line stays', async ($, on) => {
  const w = world(on)
  doubleWriter(w)
  w.mvFails.value = true
  await setupRun($, w)

  expect(w.files.has(`${SETTINGS}.census-mod.tmp`)).toBe(false)
  expect(w.files.get(SETTINGS)).toBe(settings())
  expect(saved(w)).toMatchObject({ record: 'no' })
  expect(w.logs.join('\n')).toContain('could not write /cfg/settings.json, so I left your status line alone')
})

test('an existing backup of a DIFFERENT status line is never overwritten: the removal is refused, naming it', async ($, on) => {
  const w = world(on)
  doubleWriter(w)
  const older = JSON.stringify({ statusLine: { type: 'command', command: 'older.sh' }, removedAt: 'x', from: SETTINGS })
  w.files.set(BACKUP, older)
  await setupRun($, w)

  expect(w.files.get(BACKUP)).toBe(older)
  expect(w.files.get(SETTINGS)).toBe(settings())
  expect(saved(w)).toMatchObject({ record: 'no' })
  expect(w.logs.join('\n')).toContain(`already holds a different status line (${BACKUP})`)
})

test('an existing backup of the SAME status line is fine to refresh', async ($, on) => {
  const w = world(on)
  doubleWriter(w)
  w.files.set(BACKUP, JSON.stringify({ statusLine: STATUS_LINE, removedAt: 'x', from: SETTINGS }))
  await setupRun($, w)

  expect(JSON.parse(w.files.get(SETTINGS) ?? '{}')).toEqual({ model: 'opus', env: { A: '1' } })
})

test('a dismissed /census-setup counts as offered: the next session does not offer again', async ($, on) => {
  const w = world(on)
  w.store.delete('census-mod:setup')
  w.answer.value = () => null
  await $.session.start(START)
  await w.clock.advance(0)
  await $.command.run({ command: 'census-setup', args: '', origin: { kind: 'composer' } } as never)
  for (let i = 0; i < 6; i++) await w.clock.advance(0)

  expect(saved(w).offered).toBe(true)
})

test('the vitals line appears only when this census build ships vitals', async ($, on) => {
  const w = world(on)
  await setupRun($, w)

  expect(w.logs.join('\n')).not.toContain('/census:vitals')
  expect(w.logs.at(-1)).toContain('undo any time')
})

test('"Below" is stored, and the summary says so', async ($, on) => {
  const w = world(on)
  w.answer.value = q => (q.header === '🎛️ Draw' ? pick(w, 'Yes — below')(q) : q.options[0] ?? null)
  await setupRun($, w)

  expect(saved(w)).toMatchObject({ placement: 'below' })
  expect(w.logs.join('\n')).toContain('band: on, below the input')
})

test('"No" to drawing stores draw off and no placement', async ($, on) => {
  const w = world(on)
  w.answer.value = q => (q.header === '🎛️ Draw' ? 'No — record only, draw nothing' : q.options[0] ?? null)
  await setupRun($, w)

  expect(saved(w)).toMatchObject({ draw: false })
  expect(saved(w)).not.toHaveProperty('placement')
})

test('"Above" is stored as the band', async ($, on) => {
  const w = world(on)
  w.answer.value = q => (q.header === '🎛️ Draw' ? pick(w, 'Yes — above')(q) : q.options[0] ?? null)
  await setupRun($, w)

  expect(saved(w)).toMatchObject({ draw: true, placement: 'above' })
})

test('with nothing recording into census yet there is no Shadow and no Replace: just Yes or No', async ($, on) => {
  const w = world(on)
  await setupRun($, w)
  const options = w.asks.find(a => a.header === '📝 Record')?.options ?? []

  expect(options).toEqual(['Yes — record into census (dashboards, vitals and liveness use it) (Recommended)', "No — don't record (dashboards and vitals won't see this account)"])
})

test('where the status line already feeds census: Replace first, then Shadow, Yes, No, with the long question', async ($, on) => {
  const w = world(on)
  doubleWriter(w)
  await setupRun($, w)

  expect(w.asks.find(a => a.header === '📝 Record')).toEqual({
    header: '📝 Record',
    question: "Your status line already records this account's sessions into census — the store the overseer dashboard, /census:vitals and liveness read. Replace it with census-mod (records and draws the line; yours is backed up), compare first, or leave recording to your status line?",
    options: [
      'Replace my status line — census-mod records and draws it (Recommended)',
      "Shadow — record into a separate store to compare; dashboards won't see it",
      'Yes — record into census (dashboards, vitals and liveness use it)',
      "No — don't record (dashboards and vitals won't see this account)",
    ],
  })
})

test('another writer active in the last few minutes (but not this status line) also brings Shadow, without Replace', async ($, on) => {
  const w = world(on)
  w.dirs.set('/cfg/census/sessions', ['a.json'])
  w.files.set('/cfg/census/sessions/a.json', JSON.stringify({ updated_at: 1_791_000_000 - 30, payload: {} }))
  await setupRun($, w)
  const record = w.asks.find(a => a.header === '📝 Record')

  expect(record?.options.map(o => o.split(' —')[0])).toEqual(['Shadow', 'Yes', 'No'])
  expect(record?.options[0]).toContain('(Recommended)')
  expect(record?.question).toContain('into census in the last few minutes')
})

test('CENSUS_MOD_STORE still forces shadow even where Shadow was never offered', async ($, on) => {
  const w = world(on, { env: { CLAUDE_CONFIG_DIR: '/cfg', HOME: '/home/u', CENSUS_MOD_STORE: '/cfg/census-x' } })
  await setupRun($, w)

  expect(w.asks.find(a => a.header === '📝 Record')?.options.join('|')).not.toContain('Shadow')
  expect(w.logs.join('\n')).toContain('recording: shadow store /cfg/census-x')
})
