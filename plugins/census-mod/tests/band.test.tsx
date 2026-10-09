import { expect, test } from 'claude-code/testing'
import { BAND, HINT, START, USAGE, bandLines, classicStart, turn, world } from './world'

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
  expect(lines[1]).toMatch(/^✻ Opus 5\.5 │ 🌿 main │ 📁 \/repo │ ✏️ 1  ⬆️ 1$/)
  await ui.unmount()
})

test('CENSUS_STATUSLINE_SEGMENTS reorders and splits lines with "/" just as census does', async ($, on) => {
  const w = world(on, { env: { CLAUDE_CONFIG_DIR: '/cfg', HOME: '/home/u', CENSUS_STATUSLINE_SEGMENTS: 'model,git/context' } })
  await $.session.start(START)
  await w.clock.advance(0)
  const ui = await $.ui.mount(BAND())

  expect(await bandLines(ui)).toEqual(['✻ Opus 5.5 │ 🌿 main', '🧠 •ᗧ•••••••• 9%'])
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

// ---- below the input -----------------------------------------------------------------------------------------

test('above (the default) leaves the hint line to the engine', async ($, on) => {
  const w = world(on)
  w.below.text = 'ENGINE HINT'
  await $.session.start(START)
  await w.clock.advance(0)
  const ui = await $.ui.mount(HINT())

  expect(await bandLines(ui)).toEqual(['ENGINE HINT'])
  await ui.unmount()
})

test('below: the engine\'s line first, our two rows under it, and the band above the input stays out of it', async ($, on) => {
  const w = world(on)
  w.store.set('census-mod:setup', { offered: true, placement: 'below' })
  w.below.text = '⏸ manual mode on · ? for shortcuts'
  await $.session.start(START)
  await w.clock.advance(0)

  const hint = await $.ui.mount(HINT())
  const rows = await bandLines(hint)
  expect(rows).toHaveLength(3)
  expect(rows[0]).toBe('⏸ manual mode on · ? for shortcuts') // never on the pill's line
  expect(rows[1]).toMatch(/^🧠 /)
  expect(rows[2]).toMatch(/^✻ Opus 5\.5 │ 🌿 main/)
  await hint.unmount()

  const above = await $.ui.mount(BAND())
  expect(await bandLines(above)).toEqual(['⏸ manual mode on · ? for shortcuts'])
  await above.unmount()
})

test('below still draws while the person types or the model works', async ($, on) => {
  const w = world(on)
  w.store.set('census-mod:setup', { offered: true, placement: 'below' })
  await $.session.start(START)
  await w.clock.advance(0)
  for (const props of [{ isDraft: true }, { isWorking: true }]) {
    const ui = await $.ui.mount(HINT(props))
    expect((await bandLines(ui)).length).toBe(2)
    await ui.unmount()
  }
})

test('below clips its rows to the width it is drawn in', async ($, on) => {
  const w = world(on)
  w.store.set('census-mod:setup', { offered: true, placement: 'below' })
  await $.session.start(START)
  await w.clock.advance(0)
  const ui = await $.ui.mount(HINT({}, { columns: 40, rows: 24 }))
  const rows = await bandLines(ui)

  expect(rows[0]).toBe('🧠 •ᗧ•••••••• 9% │ 💸 ᗧ$$$$$$$$$ $0.90')
  await ui.unmount()
})

test('CENSUS_MOD_PLACEMENT outranks the answer; nothing is drawn below before a session is bound', async ($, on) => {
  const w = world(on, { env: { CLAUDE_CONFIG_DIR: '/cfg', HOME: '/home/u', CENSUS_MOD_PLACEMENT: 'below' } })
  w.store.set('census-mod:setup', { offered: true, placement: 'above' })
  const early = await $.ui.mount(HINT())
  expect(await bandLines(early)).toEqual([])
  await early.unmount()

  await $.session.start(START)
  await w.clock.advance(0)
  const hint = await $.ui.mount(HINT())
  expect((await bandLines(hint)).length).toBe(2)
  await hint.unmount()
  const band = await $.ui.mount(BAND())
  expect(await bandLines(band)).toEqual([])
  await band.unmount()
})
