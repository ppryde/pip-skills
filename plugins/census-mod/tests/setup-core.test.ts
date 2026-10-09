import { expect, test } from 'claude-code/testing'
import {
  NO_DETECTION, PRESETS, placementFrom, Q, commandIsCensus, continueAnyway, enabledCensusPlugins, effective, hasIngestBlock, parseSettings, presetFrom, recordFrom,
  backupBlocks, removeStatusLine, restoreStatusLine, scriptCandidates, statusLineCommand, writerActive, writersFrom,
} from '../plugin/core/setup'

const WITH_BLOCK = { ...NO_DETECTION, ingestBlock: true }
const CFG = '/home/u/.claude'

// ---- defaults and precedence -------------------------------------------------------------------

test('before any answer: record to the real store only when the status line has no census ingest block; draw yes; gh yes', async () => {
  expect(effective({}, {}, NO_DETECTION, CFG)).toEqual({ record: 'yes', shadowDir: null, draw: true, placement: 'above', segments: undefined, pr: true })
  expect(effective({}, {}, WITH_BLOCK, CFG)).toMatchObject({ record: 'no', draw: true, pr: true })
})

test('an answer replaces the default', async () => {
  expect(effective({ record: 'yes' }, {}, WITH_BLOCK, CFG).record).toBe('yes')
  expect(effective({ record: 'no' }, {}, NO_DETECTION, CFG).record).toBe('no')
  expect(effective({ record: 'shadow' }, {}, NO_DETECTION, CFG)).toMatchObject({ record: 'shadow', shadowDir: '/home/u/.claude/census-shadow' })
  expect(effective({ draw: false, pr: false, preset: 'minimal' }, {}, NO_DETECTION, CFG)).toMatchObject({ draw: false, pr: false, segments: 'context,limits/git' })
})

test('the environment replaces the answer: CENSUS_MOD_STORE is shadow mode, CENSUS_STATUSLINE_SEGMENTS is the layout', async () => {
  const e = effective({ record: 'no', preset: 'compact' }, { CENSUS_MOD_STORE: '~/shadow', CENSUS_STATUSLINE_SEGMENTS: 'model/git', HOME: '/home/u' }, NO_DETECTION, CFG)

  expect(e).toMatchObject({ record: 'shadow', shadowDir: '/home/u/shadow', segments: 'model/git' })
  expect(effective({}, { CENSUS_STATUSLINE_SEGMENTS: '  ' }, NO_DETECTION, CFG).segments).toBeUndefined()
})

test('shadow with nowhere to write records nothing', async () => {
  expect(effective({ record: 'shadow' }, {}, NO_DETECTION, null).record).toBe('no')
})

test('the three layouts', async () => {
  expect(PRESETS.two).toBe('context,cache,limits,cost/model,git,dir,changes,pr')
  expect(PRESETS.compact.includes('/')).toBe(false) // one line
  expect(PRESETS.minimal).toBe('context,limits/git')
})

// ---- reading this account's status line ----------------------------------------------------------

test('census recording is found in a script by its sentinel, or in the command itself', async () => {
  expect(hasIngestBlock('input=$(cat)\n# --- census: record status-line payload (managed by `census`; do not edit) ---\nprintf x | census ingest\n# --- end census ---\n')).toBe(true)
  expect(hasIngestBlock('input=$(cat)\necho hi\n')).toBe(false)
  expect(commandIsCensus('census statusline')).toBe(true)
  expect(commandIsCensus('/home/u/.local/bin/census ingest')).toBe(true)
  expect(commandIsCensus('bash ~/.claude/line.sh')).toBe(false)
})

test('the scripts a command runs, as absolute paths', async () => {
  expect(scriptCandidates('bash ~/.claude/line.sh', '/home/u')).toEqual(['/home/u/.claude/line.sh'])
  expect(scriptCandidates('"$HOME/.claude/line.sh" --x', '/home/u')).toEqual(['/home/u/.claude/line.sh'])
  expect(scriptCandidates('/opt/x/line.sh', undefined)).toEqual(['/opt/x/line.sh'])
  expect(scriptCandidates('node status.js', '/home/u')).toEqual([])
})

test('settings.json: valid JSON only; the statusLine command is read from it', async () => {
  expect(parseSettings('{ nope').ok).toBe(false)
  expect(parseSettings('[]').ok).toBe(false)
  const p = parseSettings('{"statusLine":{"type":"command","command":"bash x.sh"}}')
  expect(p.ok && statusLineCommand(p.data)).toBe('bash x.sh')
  expect(parseSettings('{}').ok && statusLineCommand({})).toBeNull()
})

test('another writer is one that wrote recently and is not the mod', async () => {
  const now = 1_000_000
  expect(writerActive([{ updatedAt: now - 60_000, hasCensusMod: false }], now)).toBe(true)
  expect(writerActive([{ updatedAt: now - 60_000, hasCensusMod: true }], now)).toBe(false)
  expect(writerActive([{ updatedAt: now - 900_000, hasCensusMod: false }], now)).toBe(false)
})

// ---- the questions -----------------------------------------------------------------------------------

const YES = 'Yes — record into census (dashboards, vitals and liveness use it)'
const NO = "No — don't record (dashboards and vitals won't see this account)"
const NO_FED = 'No — leave recording to my status line (it keeps feeding census)'
const NO_OTHER = "No — don't record (whatever else writes keeps feeding census)"
const SHADOW = "Shadow — record into a separate store to compare; dashboards won't see it"
const REPLACE = 'Replace my status line — census-mod records and draws it'
const OTHER = { ...NO_DETECTION, otherWriter: true }

test('with no existing writer the record question is just Yes (recommended) or No', async () => {
  expect(Q.record(NO_DETECTION)).toEqual({
    header: '📝 Record',
    question: "Record this account's sessions into census? That's what the overseer dashboard, /census-mod:vitals and session liveness read (context, cost, limits, git, PR) — without it they see nothing from this account.",
    options: [`${YES} (Recommended)`, NO],
  })
})

test('where the status line already feeds census: Replace (recommended), Shadow, Yes, No', async () => {
  const q = Q.record(WITH_BLOCK)

  expect(q.options).toEqual([`${REPLACE} (Recommended)`, SHADOW, YES, NO_FED])
  expect(q.question).toContain('Your status line already records this account')
  expect(q.options.map(recordFrom)).toEqual(['yes', 'shadow', 'yes', 'no'])
})

test('another writer alone brings Shadow (recommended) but not Replace', async () => {
  const q = Q.record(OTHER)

  expect(q.options).toEqual([`${SHADOW} (Recommended)`, YES, NO_OTHER])
  expect(q.question).toContain('into census in the last few minutes')
})

test('answers map back to values, recommendation marker or not', async () => {
  for (const o of Q.record(NO_DETECTION).options) expect(recordFrom(o)).not.toBeNull()
  expect(Q.record(NO_DETECTION).options.map(recordFrom)).toEqual(['yes', 'no'])
  expect(Q.preset().options.map(presetFrom)).toEqual(['two', 'compact', 'minimal'])
  expect(Q.writers(true, false).options.map(writersFrom)).toEqual(['remove', 'keep', 'both'])
  expect(Q.writers(false, false).options.map(writersFrom)).toEqual(['keep', 'both']) // no band to replace it: no removal on offer
  expect(recordFrom('something else')).toBeNull()
})

// ---- removing and restoring the statusLine --------------------------------------------------------------

const SETTINGS = `{\n    "model": "opus",\n    "statusLine": { "type": "command", "command": "bash ~/.claude/line.sh", "padding": 0 },\n    "env": { "A": "1" }\n}\n`

test('removal keeps every other key, in order and indentation, and backs up the exact value', async () => {
  const r = removeStatusLine(SETTINGS, '/home/u/.claude/settings.json', '2026-10-09T10:00:00.000Z')

  expect(r.ok).toBe(true)
  if (!r.ok) return
  expect(r.text).toBe(`{\n    "model": "opus",\n    "env": {\n        "A": "1"\n    }\n}\n`)
  expect(JSON.parse(r.backup)).toEqual({
    statusLine: { type: 'command', command: 'bash ~/.claude/line.sh', padding: 0 },
    removedAt: '2026-10-09T10:00:00.000Z',
    from: '/home/u/.claude/settings.json',
  })
})

test('removal refuses invalid JSON, and has nothing to do when there is no statusLine', async () => {
  expect(removeStatusLine('{ "a": ', '/s', 'now')).toEqual({ ok: false, reason: 'invalid' })
  expect(removeStatusLine('{"a":1}', '/s', 'now')).toEqual({ ok: false, reason: 'none' })
})

test('restore puts the statusLine back exactly, only into a settings.json that has none', async () => {
  const removed = removeStatusLine(SETTINGS, '/s', 'now')
  if (!removed.ok) throw new Error('setup')
  const back = restoreStatusLine(removed.text, removed.backup)

  expect(back.done).toBe('restored')
  if (back.done !== 'restored') return
  expect(JSON.parse(back.text)).toEqual(JSON.parse(SETTINGS))
  expect(restoreStatusLine(SETTINGS, removed.backup)).toEqual({ done: 'already' })
  expect(restoreStatusLine('{"statusLine":{"type":"command","command":"other"}}', removed.backup)).toEqual({ done: 'kept', why: 'present' })
  expect(restoreStatusLine('{ nope', removed.backup)).toEqual({ done: 'kept', why: 'invalid' })
  expect(restoreStatusLine('{}', null)).toEqual({ done: 'kept', why: 'no-backup' })
  expect(restoreStatusLine('{}', 'not json')).toEqual({ done: 'kept', why: 'no-backup' })
})

test('an existing backup blocks a removal only when it holds a different status line', async () => {
  const mk = (command: string) => JSON.stringify({ statusLine: { type: 'command', command } })

  expect(backupBlocks(null, mk('a'))).toBe(false)
  expect(backupBlocks(mk('a'), mk('a'))).toBe(false)
  expect(backupBlocks(mk('a'), mk('b'))).toBe(true)
  expect(backupBlocks('not json', mk('b'))).toBe(false) // nothing worth keeping
  expect(backupBlocks('{}', mk('b'))).toBe(false)
})

// ---- review round: Windows and odd input ------------------------------------------------------------

test('on Windows census installs its launcher: python "<census dir>\\launcher.py" statusline is census recording', async () => {
  expect(commandIsCensus('python "C:\\Users\\u\\.claude\\census\\launcher.py" statusline')).toBe(true)
  expect(commandIsCensus('python C:\\Users\\u\\.claude\\census\\launcher.py ingest')).toBe(true)
  expect(commandIsCensus('C:\\bin\\census.exe ingest')).toBe(true)
  expect(commandIsCensus('python C:\\x\\other.py statusline')).toBe(false)
})

test('scripts a Windows command runs: drive and UNC paths, quoted with spaces, ~\\ and %USERPROFILE%', async () => {
  expect(scriptCandidates('powershell -File "C:\\Users\\u\\my line.ps1"', 'C:\\Users\\u')).toEqual(['C:\\Users\\u\\my line.ps1'])
  expect(scriptCandidates('bash ~\\.claude\\line.sh', 'C:\\Users\\u')).toEqual(['C:\\Users\\u\\.claude\\line.sh'])
  expect(scriptCandidates('"%USERPROFILE%\\line.cmd"', 'C:\\Users\\u')).toEqual(['C:\\Users\\u\\line.cmd'])
  expect(scriptCandidates('sh \\\\server\\share\\line.sh', undefined)).toEqual(['\\\\server\\share\\line.sh'])
  expect(scriptCandidates("sh '/opt/my dir/line.sh' --x", undefined)).toEqual(['/opt/my dir/line.sh'])
})

test('a backup that is a JSON scalar, array or null is no backup: restore says so instead of throwing', async () => {
  for (const junk of ['42', '"x"', 'null', '[1]', 'true']) expect(restoreStatusLine('{}', junk)).toEqual({ done: 'kept', why: 'no-backup' })
})

test('%USERPROFILE% expands from USERPROFILE itself, and only falls back to HOME when that is unset', async () => {
  expect(scriptCandidates('"%USERPROFILE%\\line.cmd"', '/home/u', 'C:\\Users\\u')).toEqual(['C:\\Users\\u\\line.cmd'])
  expect(scriptCandidates('"%USERPROFILE%\\line.cmd"', 'C:\\Users\\h', undefined)).toEqual(['C:\\Users\\h\\line.cmd'])
  expect(scriptCandidates('"$HOME/line.sh"', '/home/u', 'C:\\Users\\u')).toEqual(['/home/u/line.sh']) // $HOME stays HOME
})

// ---- placement ------------------------------------------------------------------------------------------

test('placement: the environment, then the answer, then above (an existing install does not move)', async () => {
  expect(effective({}, {}, NO_DETECTION, CFG).placement).toBe('above')
  expect(effective({ placement: 'below' }, {}, NO_DETECTION, CFG).placement).toBe('below')
  expect(effective({ placement: 'below' }, { CENSUS_MOD_PLACEMENT: 'above' }, NO_DETECTION, CFG).placement).toBe('above')
  expect(effective({ placement: 'above' }, { CENSUS_MOD_PLACEMENT: ' BELOW ' }, NO_DETECTION, CFG).placement).toBe('below')
  expect(effective({ placement: 'below' }, { CENSUS_MOD_PLACEMENT: 'sideways' }, NO_DETECTION, CFG).placement).toBe('below') // not a placement: ignored
})

test('one draw question: below (recommended), above, or not at all, mapped back to a placement', async () => {
  expect(Q.draw()).toEqual({
    header: '🎛️ Draw',
    question: 'Should census-mod draw your status line, and where?',
    options: ["Yes — below the input, under Claude Code's hint line (Recommended)", 'Yes — above the input, in the band', 'No — record only, draw nothing'],
  })
  expect(Q.draw().options.map(placementFrom)).toEqual(['below', 'above', null])
  expect(placementFrom('nope')).toBeNull()
})

// ---- review (wf #16): honest copy per shape ---------------------------------------------------------------

test('the No that leaves a recording status line active does not say the dashboards see nothing', async () => {
  for (const det of [WITH_BLOCK, OTHER]) {
    const no = Q.record(det).options.find(o => recordFrom(o) === 'no')!
    expect(no).not.toMatch(/won't see/)
    expect(no).toMatch(/keeps? feeding census|keeps feeding/)
  }
  expect(Q.record(NO_DETECTION).options.at(-1)).toBe(NO) // nothing records: the plain No stands
})

test('while CENSUS_MOD_STORE forces shadow, Replace is not offered and the question says why', async () => {
  const q = Q.record(WITH_BLOCK, true)

  expect(q.options.some(o => o.startsWith('Replace'))).toBe(false)
  expect(q.options.map(recordFrom)).toEqual(['shadow', 'yes', 'no'])
  expect(q.question).toContain('CENSUS_MOD_STORE')
  expect(q.question).toContain('stays as that store')
})

test('CENSUS_MOD_STORE changes nothing for the shapes that never offered Replace', async () => {
  expect(Q.record(NO_DETECTION, true)).toEqual(Q.record(NO_DETECTION))
  expect(Q.record(OTHER, true)).toEqual(Q.record(OTHER))
})


test('the enabled census plugins of any marketplace are found in enabledPlugins; census-mod and disabled ones are not', async () => {
  expect(enabledCensusPlugins({ enabledPlugins: { 'census@pip-skills': true, 'census@wf-claude-market': true, 'census@x': false, 'census-mod@pip-skills': true, other: true } }))
    .toEqual(['census@pip-skills', 'census@wf-claude-market'])
  for (const junk of [{}, { enabledPlugins: [] }, { enabledPlugins: 'x' }, { enabledPlugins: null }]) expect(enabledCensusPlugins(junk)).toEqual([])
})

test('the exclusivity question names every enabled census and how to disable it; Stop is recommended', async () => {
  const q = Q.exclusive(['census@a', 'census@b'])
  expect(q.header).toBe('⚠️ census')
  expect(q.question).toContain('claude plugin disable census@a; claude plugin disable census@b')
  expect(q.options).toEqual(["Stop — I'll disable census first (Recommended)", 'Continue anyway (two writers)'])
  expect(q.options.map(continueAnyway)).toEqual([false, true])
})

test('/census-mod:vitals is always named in the record question: it is bundled', async () => {
  for (const det of [NO_DETECTION, WITH_BLOCK, OTHER]) expect(Q.record(det).question).toContain('/census-mod:vitals')
})
