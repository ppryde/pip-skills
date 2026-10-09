import { expect, test } from 'claude-code/testing'
import { TONE_COLOR, draw, displayWidth, fit, fmtReset, layout, levelTone, levelToneInv, lineWidth, pacBar, plain, roundHalfEven } from '../plugin/core/render'
import type { RenderInput } from '../plugin/core/render'

// The goldens below are census's own render.py output (NO_COLOR) for the same inputs.
const NOW = 1_791_000_000
const FULL: RenderInput = {
  now: NOW,
  ctxPct: 42,
  cache: { hitRatio: 0.93, requests: 12, warm: true, expiresAt: NOW + 50 * 60, misses: 0 },
  limits: {
    five_hour: { used_percentage: 77.5, resets_at: NOW + 2 * 3600 + 600 },
    seven_day: { used_percentage: 24, resets_at: NOW + 3 * 86400 + 4 * 3600 },
  },
  costUsd: 3.1,
  durationMs: 6_480_000,
  modelName: 'Opus 5.5',
  git: { branch: 'feat/x', uncommitted: 3, ahead: 2, hasUpstream: true },
  pr: null,
  cwd: '/Users/philip.pryde/repos/pip-skills',
  env: { CLAUDE_CONFIG_DIR: '/home/u/.claude-personal' },
}
const text = (i: RenderInput) => draw(i).map(plain).join('\n')

test('the default band is render.py\'s two lines, glyph for glyph', async () => {
  expect(text(FULL)).toBe(
    [
      '🧠 ••••ᗧ••••• 42% │ 🎯 93% ⟳ 50m │ ⏳ ••••••••ᗧ• 78% ⟳ 2h10m │ 📅 ••ᗧ••••••• 24% ⟳ 3d4h │ 💸 ••ᗧ$$$$$$$ $3.10 │ 🐌 $1.72/hr',
      '✻  Opus 5.5 │ 🌿 feat/x │ 📁 …/philip.pryde/repos/pip-skills │ ✏️ 3  ⬆️ 2',
    ].join('\n'),
  )
})

test('CENSUS_STATUSLINE_SEGMENTS: "," joins on a line, "/" starts the next, unknown names are dropped', async () => {
  expect(layout('context,nope/ model , cache')).toEqual([['context'], ['model', 'cache']])
  expect(layout(undefined)).toEqual([['context', 'cache', 'limits', 'cost'], ['model', 'git', 'dir', 'changes', 'pr']])
  expect(layout('  ')[0]).toContain('context')
  expect(text({ ...FULL, env: { ...FULL.env, CENSUS_STATUSLINE_SEGMENTS: 'context,model/limits,git' } })).toBe(
    ['🧠 ••••ᗧ••••• 42% │ ✻  Opus 5.5', '⏳ ••••••••ᗧ• 78% ⟳ 2h10m │ 📅 ••ᗧ••••••• 24% ⟳ 3d4h │ 🌿 feat/x'].join('\n'),
  )
})

test('hot figures turn red, a cold cache is a 🧊 with its misses, a runaway burn is a 🚀', async () => {
  const hot: RenderInput = {
    ...FULL, ctxPct: 95, cache: { hitRatio: 0.5, requests: 3, warm: false, expiresAt: null, misses: 2 }, limits: {},
    costUsd: 30, durationMs: 3_600_000, git: { branch: 'main', uncommitted: 0, ahead: 0, hasUpstream: false }, cwd: '/a/b', env: {},
  }

  expect(text(hot)).toBe(['🧠 •••••••••ᗧ 95% │ 🧊 50% ✗2 │ 💸 •••••••••ᗧ $30.00 │ 🚀 $30.00/hr', '✻  Opus 5.5 │ 🌿 main │ 📁 /a/b │ ✏️ 0'].join('\n'))
  expect(draw(hot)[0]?.find(r => r.t === '95%')?.tone).toBe('red')
  expect(draw(hot)[0]?.find(r => r.t === '50%')?.tone).toBe('red') // the inverted ramp: low is bad
})

test('nothing known yet draws the empty gauge, the default model and no git', async () => {
  const bare: RenderInput = { ...FULL, ctxPct: null, cache: { hitRatio: null, requests: 0, warm: false, expiresAt: null, misses: 0 }, limits: {}, costUsd: null, durationMs: null, modelName: null, git: null, cwd: '/a', env: { CENSUS_STATUSLINE_MASCOT: 'X' } }

  expect(text(bare)).toBe(['🧠 ᗧ••••••••• --%', 'X Claude │ 📁 /a'].join('\n'))
})

test('an expired window is not drawn, and a PR rides on the branch', async () => {
  const lines = text({ ...FULL, limits: { five_hour: { used_percentage: 50, resets_at: NOW - 1 } }, pr: { number: 12, url: 'u' } })

  expect(lines).not.toContain('⏳')
  expect(lines).toContain('🌿 feat/x')
  expect(lines).not.toContain('PR #') // the PR is its own segment now
})

test('thresholds and rounding are render.py\'s', async () => {
  expect([levelTone(74), levelTone(75), levelTone(89), levelTone(90)]).toEqual(['green', 'orange', 'orange', 'red'])
  expect([levelToneInv(74), levelToneInv(75), levelToneInv(90)]).toEqual(['red', 'orange', 'green'])
  expect([0.5, 1.5, 2.5, 77.5, 12.4].map(roundHalfEven)).toEqual([0, 2, 2, 78, 12])
  expect(fmtReset(NOW + 59, NOW)).toBe('0m')
  expect(fmtReset(NOW + 3600, NOW)).toBe('1h0m')
  expect(fmtReset(NOW + 86400, NOW)).toBe('1d0h')
  expect(plain(pacBar(0))).toBe('ᗧ•••••••••')
  expect(plain(pacBar(100))).toBe('•••••••••ᗧ')
  expect(pacBar(100).map(r => r.tone)).toEqual(['green', 'green', 'green', 'green', 'green', 'green', 'green', 'orange', 'red', 'pac'])
})

test('a line that is too wide loses whole trailing parts, never half of one', async () => {
  const [first] = draw(FULL)
  const wide = lineWidth(first ?? [])
  const cut = fit(first ?? [], 60)

  expect(wide).toBeGreaterThan(60)
  expect(lineWidth(cut)).toBeLessThanOrEqual(60)
  expect(plain(cut).endsWith('⟳ 2h10m')).toBe(true)
  expect(plain(fit(first ?? [], 500))).toBe(plain(first ?? []))
  expect(plain(fit(first ?? [], 3))).toBe('🧠 ••••ᗧ••••• 42%') // one part always stays; the surface truncates it
})

test('emoji and CJK count two columns, a variation selector widens its base', async () => {
  expect(displayWidth('ab')).toBe(2)
  expect(displayWidth('🧠')).toBe(2)
  expect(displayWidth('⏳')).toBe(2)
  expect(displayWidth('✏️')).toBe(2)
  expect(displayWidth('日本')).toBe(4)
  expect(displayWidth('ᗧ•⟳')).toBe(3)
})

test('CLAUDE_COST_BUDGET must parse whole: "5oops" is the default budget, not $5', async () => {
  const cost = (budget: string) => text({ ...FULL, costUsd: 10, env: { ...FULL.env, CLAUDE_COST_BUDGET: budget }, ...{} }).split('\n')[0]
  expect(cost('5oops')).toBe(cost('20'))
  expect(cost('5')).not.toBe(cost('20'))
  expect(cost(' 5 ')).toBe(cost('5'))
  expect(cost('')).toBe(cost('20'))
})

test('segment names are looked up as own properties: __proto__, constructor and toString are dropped, never called', async () => {
  expect(layout('__proto__,constructor,toString,context')).toEqual([['context']])
  expect(() => draw({ ...FULL, env: { CENSUS_STATUSLINE_SEGMENTS: '__proto__,hasOwnProperty,model' } })).not.toThrow()
})

test('a joined emoji (a ZWJ sequence) is one glyph wide, not one per part', async () => {
  expect(displayWidth('👩‍💻')).toBe(2)
  expect(displayWidth('👨‍👩‍👧')).toBe(2)
  expect(displayWidth('a👩‍💻b')).toBe(4)
  expect(displayWidth('❤️')).toBe(2)
})

test('the mascot is a ✻ in Claude\'s orange, as its own coloured run; an override is plain text', async () => {
  const head = (env: RenderInput['env']) => draw({ ...FULL, env }).at(1)?.slice(0, 2)

  expect(head({})).toEqual([{ t: '✻ ', tone: 'claude', bold: true }, { t: ' ' }]) // bold, and a two-column slot like an emoji
  expect(head({ CLAUDE_CONFIG_DIR: '/h/.claude-personal', CLAUDE_PROFILE: 'personal' })).toEqual([{ t: '✻ ', tone: 'claude', bold: true }, { t: ' ' }]) // the account no longer picks it
  expect(head({ CENSUS_STATUSLINE_MASCOT: '🐙' })).toEqual([{ t: '🐙 ' }, { t: 'Opus 5.5', tone: 'cyan' }])
  expect(TONE_COLOR.claude).toBe('#D97757')
})

const PR = { number: 12, url: 'u', reviewState: 'approved' }
const lineTwo = (pr: RenderInput['pr'], env: RenderInput['env'] = FULL.env) => draw({ ...FULL, pr, env }).at(1) ?? []

test('the PR segment ends line two by default: 🔀 #N and the review state, green / yellow / red; hidden without a PR', async () => {
  expect(plain(lineTwo(PR))).toMatch(/✏️ 3  ⬆️ 2 │ 🔀 #12 approved$/)
  expect(lineTwo(PR).find(r => r.t === 'approved')?.tone).toBe('green')
  expect(lineTwo({ ...PR, reviewState: 'pending' }).find(r => r.t === 'pending')?.tone).toBe('yellow')
  expect(lineTwo({ ...PR, reviewState: 'changes_requested' }).find(r => r.t === 'changes_requested')?.tone).toBe('red')
  expect(plain(lineTwo({ number: 7, url: 'u' }))).toMatch(/🔀 #7$/)
  expect(text({ ...FULL, pr: null })).not.toContain('🔀')
  expect(plain(lineTwo(PR, { ...FULL.env, CENSUS_STATUSLINE_SEGMENTS: 'model,git' }))).not.toContain('🔀')
})

test('the ✻ slot is two columns wide, so the model name lines up under emoji-led segments', async () => {
  expect(displayWidth('✻ ')).toBe(2)
  expect(displayWidth('✻  Opus')).toBe(displayWidth('🦾 Opus'))
})
