import { expect, test } from 'claude-code/testing'
import { BAND, START, USAGE, bandLines, classicStart, turn, world } from './world'

const SEC = 1000
const MIN = 60 * SEC

test('the band draws census\'s two lines from live engine figures', async ($, on) => {
  const w = world(on, { env: { CLAUDE_CONFIG_DIR: '/home/u/.claude-personal', HOME: '/home/u' }, files: { '/home/u/.claude-personal/census/cli.path': '/c/cli.py', '/c/cli.py': '' } })
  w.usage.value = {
    ...w.usage.value,
    rateLimits: [
      { kind: 'five_hour', percentUsed: 77.5, resetsAt: new Date(1_791_000_000_000 + 2 * 3600_000 + 600_000).toISOString() },
      { kind: 'seven_day', percentUsed: 24, resetsAt: new Date(1_791_000_000_000 + (3 * 24 + 4) * 3600_000).toISOString() },
    ],
  }
  await $.session.start(START)
  await w.clock.advance(0)
  await $.turn.complete(turn(USAGE))
  await w.clock.advance(0)
  await w.clock.advance(2 * SEC)
  const ui = await $.ui.mount(BAND())
  const lines = await bandLines(ui)

  expect(lines).toHaveLength(2)
  expect(lines[0]).toMatch(/^🧠 •ᗧ•••••••• 9% │ 🎯 90% ⟳ 59m │ ⏳ ••••••••ᗧ• 78% ⟳ 2h9m │/)
  expect(lines[0]).toContain('📅 ••ᗧ••••••• 24% ⟳ 3d3h │ 💸')
  expect(lines[1]).toMatch(/^🎮 Opus 5\.5 │ 🌿 main │ 📁 \/repo │ ✏️ 1  ⬆️ 1$/)
  await ui.unmount()
})

test('CENSUS_STATUSLINE_SEGMENTS reorders and splits lines with "/" just as census does', async ($, on) => {
  const w = world(on, { env: { CLAUDE_CONFIG_DIR: '/cfg', HOME: '/home/u', CENSUS_STATUSLINE_SEGMENTS: 'model,git/context' } })
  await $.session.start(START)
  await w.clock.advance(0)
  const ui = await $.ui.mount(BAND())

  expect(await bandLines(ui)).toEqual(['🦾 Opus 5.5 │ 🌿 main', '🧠 •ᗧ•••••••• 9%'])
  await ui.unmount()
})

test('the band nests what other mods draw beneath it, and yields to a survey', async ($, on) => {
  const w = world(on)
  w.below.text = 'VIGIL BAR'
  await $.session.start(START)
  await w.clock.advance(0)

  let ui = await $.ui.mount(BAND())
  const lines = await bandLines(ui)
  expect(lines.at(-1)).toBe('VIGIL BAR')
  expect(lines[0]).toContain('🧠')
  await ui.unmount()

  ui = await $.ui.mount(BAND({ hasSurvey: true }))
  expect(await bandLines(ui)).toEqual(['VIGIL BAR'])
  await ui.unmount()
})

test('the band keeps to maxRows and to bodyColumns', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await w.clock.advance(0)

  let ui = await $.ui.mount(BAND({ maxRows: 1 }))
  expect(await bandLines(ui)).toHaveLength(1)
  await ui.unmount()
  ui = await $.ui.mount(BAND({ bodyColumns: 40 }))
  const lines = await bandLines(ui)
  expect(lines[0]).toBe('🧠 •ᗧ•••••••• 9% │ 💸 ᗧ$$$$$$$$$ $0.90')
  await ui.unmount()
})

test('nothing is drawn for a -p run or before a session is bound', async ($, on) => {
  const w = world(on)
  let ui = await $.ui.mount(BAND())
  expect(await bandLines(ui)).toEqual([])
  await ui.unmount()
  await $.session.start({ ...START, isInteractive: false })
  ui = await $.ui.mount(BAND())
  expect(await bandLines(ui)).toEqual([])
  await ui.unmount()
  void w
})

test('a 30 s tick redraws for the countdowns but never records', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await w.clock.advance(0)
  await $.turn.complete(turn(USAGE))
  await w.clock.advance(2 * SEC)
  const ingests = w.ingests.length
  const redraws = w.invalidations.count

  await w.clock.advance(5 * MIN)
  expect(w.invalidations.count).toBeGreaterThanOrEqual(redraws + 10)
  expect(w.ingests).toHaveLength(ingests)
})

test('the engine is asked to redraw when the figures move', async ($, on) => {
  const w = world(on)
  await $.session.start(START)
  await w.clock.advance(0)
  const before = w.invalidations.count
  await $.session.measure({ context: { window: 1_000_000, percent: 30 }, rateLimits: [], changed: ['context'] as never })

  expect(w.invalidations.count).toBeGreaterThan(before)
  void classicStart
})
