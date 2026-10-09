import { expect, test } from 'claude-code/testing'
import { BAND, START, bandLines, turn, USAGE, world } from './world'

const SEC = 1000

test('census-mod records with NO census plugin anywhere: its own bundled recorder, a list argv, nothing discovered', async ($, on) => {
  const w = world(on) // the fake file system holds census-mod and nothing else
  await $.session.start(START)
  await w.clock.advance(0)

  expect(w.ingests).toHaveLength(1)
  expect(w.ingests[0]?.argv).toEqual(['python3', expect.stringMatching(/\/scripts\/cli\.py$/), 'ingest'])
  const looked = w.runs.map(r => r.argv.join(' ')).filter(c => /census|which/.test(c) && !/scripts\/cli\.py/.test(c))
  expect(looked).toEqual([]) // no `command -v census`, no `where`, no sibling lookup
})

test('it never reads a cli.path, a CENSUS_CLI or a sibling plugin folder', async ($, on) => {
  const w = world(on, { env: { CLAUDE_CONFIG_DIR: '/cfg', HOME: '/home/u', CENSUS_CLI: '/opt/other/census.py' }, files: { '/cfg/census/cli.path': '/elsewhere/cli.py', '/elsewhere/cli.py': '' } })
  await $.session.start(START)
  await w.clock.advance(0)

  expect(w.ingests.at(-1)?.argv[1]).toMatch(/\/scripts\/cli\.py$/)
  expect(w.ingests.at(-1)?.argv[1]).not.toContain('/elsewhere')
  expect(w.ingests.at(-1)?.argv[1]).not.toContain('/opt/other')
  // and it never even LOOKED: no read or probe of a pointer, an override target, or a sibling census plugin
  const probes = w.lookups.filter(p => /cli\.path|\/elsewhere|\/opt\/other|\/census\/([^/]+\/)?(scripts|\.orphaned_at)/.test(p))
  expect(probes).toEqual([])
})

test('shadow mode: CENSUS_MOD_STORE is the child\'s CENSUS_STORE, the bundled recorder still does the writing', async ($, on) => {
  const w = world(on, { env: { CLAUDE_CONFIG_DIR: '/cfg', HOME: '/home/u', CENSUS_MOD_STORE: '/cfg/census-shadow' } })
  await $.session.start(START)
  await w.clock.advance(0)

  expect(w.ingests.at(-1)?.argv[1]).toMatch(/\/scripts\/cli\.py$/)
  expect(w.ingests.at(-1)?.env).toEqual({ CENSUS_STORE: '/cfg/census-shadow' })
})

test('a .json shadow store goes to the child unchanged', async ($, on) => {
  const w = world(on, { env: { CLAUDE_CONFIG_DIR: '/cfg', HOME: '/home/u', CENSUS_MOD_STORE: '/cfg/shadow/status.json' } })
  await $.session.start(START)
  await w.clock.advance(0)

  expect(w.ingests.at(-1)?.env).toEqual({ CENSUS_STORE: '/cfg/shadow/status.json' })
})

test('a missing bundle (a broken install) records nothing, says so once, and the band still draws', async ($, on) => {
  const w = world(on)
  w.bundle.present = false
  await $.session.start(START)
  await w.clock.advance(0)
  await $.turn.complete(turn(USAGE))
  await w.clock.advance(3 * SEC)

  expect(w.ingests).toHaveLength(0)
  expect(w.logs.filter(l => l.includes('bundled recorder is missing'))).toHaveLength(1)
  const ui = await $.ui.mount(BAND())
  const lines = await bandLines(ui)
  expect(lines).toHaveLength(2)
  expect(lines[0]).toContain('🧠')
  await ui.unmount()
})
