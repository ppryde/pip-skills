import { expect, test } from 'claude-code/testing'
import { CLI, START, world } from './world'

const SEC = 1000
const MIN = 60 * SEC

test('the CLI is found: the account\'s cli.path pointer, else CENSUS_CLI, else census on PATH', async ($, on) => {
  const a = world(on, { files: { '/cfg/census/cli.path': '/elsewhere/cli.py', '/elsewhere/cli.py': '' } })
  await $.session.start(START)
  await a.clock.advance(0)
  expect(a.ingests.at(-1)?.argv).toEqual(['python3', '/elsewhere/cli.py', 'ingest'])
})

test('a pointer to a file that is gone falls through to CENSUS_CLI', async ($, on) => {
  const w = world(on, { env: { CLAUDE_CONFIG_DIR: '/cfg', HOME: '/home/u', CENSUS_CLI: '/opt/census.py' }, files: { '/cfg/census/cli.path': '/gone/cli.py', '/opt/census.py': '' } })
  await $.session.start(START)
  await w.clock.advance(0)

  expect(w.ingests.at(-1)?.argv).toEqual(['python3', '/opt/census.py', 'ingest'])
})

test('with no pointer yet, the census plugin installed beside this one is found (repo layout)', async ($, on) => {
  const w = world(on)
  w.files.delete('/cfg/census/cli.path')
  w.sibling.layout = 'repo'
  await $.session.start(START)
  await w.clock.advance(0)

  expect(w.ingests.at(-1)?.argv[0]).toBe('python3')
  expect(w.ingests.at(-1)?.argv[1]).toMatch(/\/census\/scripts\/cli\.py$/)
})

test('...or in the marketplace cache: the highest version, orphans skipped', async ($, on) => {
  const w = world(on)
  w.files.delete('/cfg/census/cli.path')
  w.sibling.layout = 'cache'
  w.sibling.versions = { '0.9.0': {}, '0.10.0': {}, '0.11.0': { orphaned: true } }
  await $.session.start(START)
  await w.clock.advance(0)

  expect(w.ingests.at(-1)?.argv[1]).toMatch(/\/census\/0\.10\.0\/scripts\/cli\.py$/)
})

test('CENSUS_CLI outranks the sibling plugin, and the sibling outranks PATH', async ($, on) => {
  const a = world(on, { env: { CLAUDE_CONFIG_DIR: '/cfg', HOME: '/home/u', CENSUS_CLI: '/opt/census.py' }, files: { '/opt/census.py': '' } })
  a.files.delete('/cfg/census/cli.path')
  a.sibling.layout = 'repo'
  a.which.value = '/usr/bin/census'
  await $.session.start(START)
  await a.clock.advance(0)
  expect(a.ingests.at(-1)?.argv[1]).toBe('/opt/census.py')
})

test('the sibling outranks census on PATH', async ($, on) => {
  const w = world(on)
  w.files.delete('/cfg/census/cli.path')
  w.sibling.layout = 'repo'
  w.which.value = '/usr/bin/census'
  await $.session.start(START)
  await w.clock.advance(0)

  expect(w.ingests.at(-1)?.argv[1]).toMatch(/census\/scripts\/cli\.py$/)
  expect(w.runs.some(r => r.argv[2]?.includes('command -v census'))).toBe(false)
})

test('then census on PATH, run as the executable it is', async ($, on) => {
  const w = world(on, { files: { '/cfg/census/cli.path': '' } })
  w.files.delete('/cfg/census/cli.path')
  w.which.value = '/usr/local/bin/census'
  await $.session.start(START)
  await w.clock.advance(0)

  expect(w.ingests.at(-1)?.argv).toEqual(['/usr/local/bin/census', 'ingest'])
})

test('CENSUS_STORE moves the census dir the pointer is read from', async ($, on) => {
  const w = world(on, { env: { CLAUDE_CONFIG_DIR: '/cfg', HOME: '/home/u', CENSUS_STORE: '/store' }, files: { '/store/cli.path': '/s/cli.py', '/s/cli.py': '' } })
  await $.session.start(START)
  await w.clock.advance(0)

  expect(w.ingests.at(-1)?.argv).toEqual(['python3', '/s/cli.py', 'ingest'])
})

test('no census anywhere: nothing is recorded, one line says so, the band still draws', async ($, on) => {
  const w = world(on)
  w.files.delete('/cfg/census/cli.path')
  await $.session.start(START)
  await w.clock.advance(0)
  await $.turn.complete({ answer: 'a', durationMs: 1, isAborted: false, turnId: 't', reason: 'answer' as const })
  await w.clock.advance(3 * SEC)

  expect(w.ingests).toHaveLength(0)
  expect(w.logs.filter(l => l.includes('census not found — install the census plugin'))).toHaveLength(1)
})

test('shadow mode: CENSUS_MOD_STORE is the child\'s CENSUS_STORE, and its own pointer is read first', async ($, on) => {
  const w = world(on, {
    env: { CLAUDE_CONFIG_DIR: '/cfg', HOME: '/home/u', CENSUS_MOD_STORE: '/cfg/census-shadow' },
    files: { '/cfg/census-shadow/cli.path': '/shadow/cli.py', '/shadow/cli.py': '' },
  })
  await $.session.start(START)
  await w.clock.advance(0)

  expect(w.ingests.at(-1)?.argv).toEqual(['python3', '/shadow/cli.py', 'ingest'])
  expect(w.ingests.at(-1)?.env).toEqual({ CENSUS_STORE: '/cfg/census-shadow' })
})

test('shadow mode learns the CLI from the real census dir while its own pointer does not exist yet', async ($, on) => {
  const w = world(on, { env: { CLAUDE_CONFIG_DIR: '/cfg', HOME: '/home/u', CENSUS_MOD_STORE: '/cfg/census-shadow' } })
  await $.session.start(START)
  await w.clock.advance(0)

  expect(w.ingests.at(-1)?.argv).toEqual(['python3', CLI, 'ingest'])
  expect(w.ingests.at(-1)?.env).toEqual({ CENSUS_STORE: '/cfg/census-shadow' })
})

test('a CLI that is not found is looked for again a minute later, not on every write', async ($, on) => {
  const w = world(on)
  w.files.delete('/cfg/census/cli.path')
  await $.session.start(START)
  await w.clock.advance(0)
  const looks = () => w.runs.filter(r => r.argv[2]?.includes('command -v census')).length
  expect(looks()).toBe(1)
  await w.clock.advance(30 * SEC)
  expect(looks()).toBe(1)

  await w.clock.advance(31 * SEC)
  w.files.set('/cfg/census/cli.path', CLI)
  await $.session.measure({ context: { window: 1_000_000, percent: 50 }, rateLimits: [{ kind: 'five_hour', percentUsed: 5, resetsAt: '2026-10-09T22:00:00Z' }], changed: ['rateLimits'] as never })
  await w.clock.advance(2 * MIN)
  expect(w.ingests.at(-1)?.argv).toEqual(['python3', CLI, 'ingest'])
})
