// The status line as data: a port of census's render.py (segments, glyphs, thresholds, the `/` line
// syntax). A line is a list of runs; the shell turns runs into <Text>, tests read them as text.
import type { GitState, Pr } from './types'

export type Tone = 'grey' | 'cyan' | 'green' | 'yellow' | 'magenta' | 'pac' | 'white' | 'red' | 'orange' | 'claude'
export type Run = { t: string; tone?: Tone }
export type Line = Run[]

/** render.py's ANSI palette as Text colours (names the surface's chalk-style colours accept; orange is 256-colour 208). */
export const TONE_COLOR: Record<Tone, string> = {
  grey: 'gray', cyan: 'cyan', green: 'green', yellow: 'yellow', magenta: 'magenta',
  pac: 'yellowBright', white: 'whiteBright', red: 'red', orange: '#ff8700',
  claude: '#D97757', // the asterisk's own orange (proven live as a raw hex Text colour)
}

export type RenderEnv = {
  CENSUS_STATUSLINE_SEGMENTS?: string
  CENSUS_STATUSLINE_MASCOT?: string
  CLAUDE_COST_BUDGET?: string
  CLAUDE_PROFILE?: string
  CLAUDE_CONFIG_DIR?: string
}

export type RenderInput = {
  now: number // epoch seconds
  ctxPct: number | null
  cache: { hitRatio: number | null; requests: number; warm: boolean; expiresAt: number | null; misses: number }
  limits: Record<string, { used_percentage: number; resets_at: number } | undefined>
  costUsd: number | null
  durationMs: number | null
  modelName: string | null
  git: Pick<GitState, 'branch' | 'uncommitted' | 'ahead' | 'hasUpstream'> | null
  pr: Pr | null
  cwd: string
  env: RenderEnv
}

export const DEFAULT_SEGMENTS = 'context,cache,limits,cost/model,git,dir,changes,pr'
export const DEFAULT_BUDGET = 20
export const BAR_WIDTH = 10

/** printf "%.0f": round half to even. */
export function roundHalfEven(x: number): number {
  const f = Math.floor(x)
  const d = x - f
  if (d < 0.5) return f
  if (d > 0.5) return f + 1
  return f % 2 === 0 ? f : f + 1
}

export const levelTone = (pct: number): Tone => (pct >= 90 ? 'red' : pct >= 75 ? 'orange' : 'green')
export const levelToneInv = (pct: number): Tone => (pct >= 90 ? 'green' : pct >= 75 ? 'orange' : 'red')

export function pacBar(pct: number, width = BAR_WIDTH, glyph = '•', ahead?: string): Run[] {
  const track = ahead ?? glyph
  const filled = Math.max(0, Math.min(Math.floor((pct / 100) * width + 0.5), width))
  const pac = Math.min(filled, width - 1)
  const out: Run[] = []
  for (let j = 0; j < width; j++) {
    if (j < pac) out.push({ t: glyph, tone: levelTone(Math.floor(((j + 1) * 100) / width)) })
    else if (j === pac) out.push({ t: 'ᗧ', tone: 'pac' })
    else out.push({ t: track, tone: 'white' })
  }
  return out
}

export function fmtReset(target: number, now: number): string {
  const diff = Math.max(0, Math.floor(target - now))
  if (diff >= 86400) return `${Math.floor(diff / 86400)}d${Math.floor((diff % 86400) / 3600)}h`
  if (diff >= 3600) return `${Math.floor(diff / 3600)}h${Math.floor((diff % 3600) / 60)}m`
  return `${Math.floor(diff / 60)}m`
}

const sp: Run = { t: ' ' }
const grey = (t: string): Run => ({ t, tone: 'grey' })

function segContext(i: RenderInput): Line[] {
  if (i.ctxPct === null) {
    return [[grey('🧠'), sp, { t: 'ᗧ', tone: 'pac' }, { t: '•'.repeat(BAR_WIDTH - 1), tone: 'white' }, sp, grey('--%')]]
  }
  const shown = roundHalfEven(i.ctxPct)
  return [[grey('🧠'), sp, ...pacBar(i.ctxPct), sp, { t: `${shown}%`, tone: levelTone(shown) }]]
}

function segCache(i: RenderInput): Line[] {
  const { hitRatio, requests, warm, expiresAt, misses } = i.cache
  if (hitRatio === null || !(requests > 0)) return []
  const pct = roundHalfEven(Math.max(0, Math.min(100, hitRatio * 100)))
  const line: Line = [grey(warm ? '🎯' : '🧊'), sp, { t: `${pct}%`, tone: levelToneInv(pct) }]
  if (warm && expiresAt !== null) line.push(sp, grey(`⟳ ${fmtReset(expiresAt, i.now)}`))
  if (misses > 0) line.push(sp, { t: `✗${misses}`, tone: 'red' })
  return [line]
}

function usageBar(i: RenderInput, w: { used_percentage: number; resets_at: number }): Line {
  const shown = roundHalfEven(w.used_percentage)
  return [...pacBar(w.used_percentage), sp, { t: `${shown}%`, tone: levelTone(shown) }, sp, grey(`⟳ ${fmtReset(w.resets_at, i.now)}`)]
}

function segLimits(i: RenderInput): Line[] {
  const out: Line[] = []
  for (const [key, emoji] of [['five_hour', '⏳'], ['seven_day', '📅']] as const) {
    const w = i.limits[key]
    if (!w) continue
    if (w.resets_at <= i.now) continue // an expired window is a fossil
    out.push([grey(emoji), sp, ...usageBar(i, w)])
  }
  return out
}

function budget(env: RenderEnv): number {
  // The whole value or nothing: "5oops" is not a $5 budget.
  const t = (env.CLAUDE_COST_BUDGET ?? '').trim()
  const v = /^-?\d+(\.\d+)?$/.test(t) ? Number(t) : Number.NaN
  return Number.isFinite(v) ? v : DEFAULT_BUDGET
}

function segCost(i: RenderInput): Line[] {
  if (i.costUsd === null) return []
  const b = budget(i.env)
  const pct = b <= 0 ? 0 : Math.max(0, roundHalfEven((i.costUsd / b) * 100))
  const out: Line[] = [[grey('💸'), sp, ...pacBar(Math.min(pct, 100), BAR_WIDTH, '•', '$'), sp, { t: `$${i.costUsd.toFixed(2)}`, tone: levelTone(pct) }]]
  if (i.durationMs !== null && i.durationMs > 0) {
    const burn = i.costUsd / (i.durationMs / 3_600_000)
    const bi = roundHalfEven(burn)
    const [tone, emoji]: [Tone, string] = bi >= 20 ? ['red', '🚀'] : bi >= 8 ? ['orange', '🔥'] : ['green', '🐌']
    out.push([{ t: `${emoji} ` }, { t: `$${bi >= 100 ? String(bi) : burn.toFixed(2)}/hr`, tone }])
  }
  return out
}

export function detectAccount(env: RenderEnv): 'personal' | 'work' {
  if (env.CLAUDE_PROFILE) return ['personal', 'home', 'p'].includes(env.CLAUDE_PROFILE) ? 'personal' : 'work'
  if (env.CLAUDE_CONFIG_DIR) return env.CLAUDE_CONFIG_DIR.includes('personal') ? 'personal' : 'work'
  return 'work'
}

export const DEFAULT_MASCOT = '✻'
export const mascot = (env: RenderEnv): string => env.CENSUS_STATUSLINE_MASCOT || DEFAULT_MASCOT

function segModel(i: RenderInput): Line[] {
  const custom = i.env.CENSUS_STATUSLINE_MASCOT
  // The default is a coloured run of its own; an override is drawn as given.
  const glyph: Run = custom ? { t: `${custom} ` } : { t: DEFAULT_MASCOT, tone: 'claude' }
  return [[glyph, ...(custom ? [] : [sp]), { t: i.modelName || 'Claude', tone: 'cyan' }]]
}

function segGit(i: RenderInput): Line[] {
  if (!i.git?.branch) return []
  return [[{ t: `🌿 ${i.git.branch}`, tone: 'green' }]]
}

function segDir(i: RenderInput): Line[] {
  const parts = i.cwd.split(/[\\/]/)
  const shown = parts.length <= 3 ? i.cwd : `…${parts.slice(-3).map(p => `/${p}`).join('')}`
  return [[{ t: `📁 ${shown}`, tone: 'magenta' }]]
}

function segChanges(i: RenderInput): Line[] {
  if (!i.git?.branch) return []
  const line: Line = [{ t: `✏️ ${i.git.uncommitted}`, tone: 'yellow' }]
  if (i.git.ahead > 0 && i.git.hasUpstream) line.push({ t: '  ' }, { t: `⬆️ ${i.git.ahead}`, tone: 'yellow' })
  return [line]
}

const REVIEW_TONE: Record<string, Tone> = { approved: 'green', pending: 'yellow', changes_requested: 'red' }

/** The branch's open PR (from the mod's gh cache): `🔀 #12 approved`, the state coloured; hidden without one. */
function segPr(i: RenderInput): Line[] {
  if (!i.pr || !(i.pr.number > 0)) return []
  const line: Line = [{ t: `🔀 #${i.pr.number}` }]
  if (i.pr.reviewState) line.push(sp, { t: i.pr.reviewState, tone: REVIEW_TONE[i.pr.reviewState] ?? 'grey' })
  return [line]
}

export const SEGMENTS: Record<string, (i: RenderInput) => Line[]> = {
  context: segContext, cache: segCache, limits: segLimits, cost: segCost, model: segModel, git: segGit, dir: segDir, changes: segChanges, pr: segPr,
}

/** The configured segments as lines of names; `/` starts a new line, unknown names are dropped. */
export function layout(spec: string | undefined): string[][] {
  const text = spec?.trim() || DEFAULT_SEGMENTS
  return text.split('/').map(line => line.split(',').map(s => s.trim()).filter(n => Object.hasOwn(SEGMENTS, n)))
}

const SEPARATOR: Run = { t: ' │ ', tone: 'grey' }

/** Each configured line as runs, parts joined by the grey bar; an empty line is dropped. */
export function draw(i: RenderInput): Line[] {
  const lines: Line[] = []
  for (const names of layout(i.env.CENSUS_STATUSLINE_SEGMENTS)) {
    const parts = names.flatMap(n => (Object.hasOwn(SEGMENTS, n) ? SEGMENTS[n]?.(i) : undefined) ?? [])
    if (parts.length) lines.push(parts.flatMap((p, k) => (k === 0 ? p : [SEPARATOR, ...p])))
  }
  return lines
}

export const plain = (line: Line): string => line.map(r => r.t).join('')

/** Terminal columns a string takes: wide emoji and CJK count 2, a variation selector widens its base. */
export function displayWidth(text: string): number {
  let w = 0
  let joined = false // after a zero-width joiner the next emoji is part of the same grapheme
  for (const ch of text) {
    const cp = ch.codePointAt(0) ?? 0
    if (joined) {
      joined = false
      if (cp >= 0x1f000 || WIDE_BMP.has(cp) || cp === 0x2640 || cp === 0x2642 || cp === 0x2695 || cp === 0x2764) continue
    }
    if (cp === 0x200d) joined = true
    if (cp === 0xfe0f) w += 1
    else if (cp === 0x200d || (cp >= 0x300 && cp <= 0x36f)) w += 0
    else if (cp >= 0x1f000 || (cp >= 0x2e80 && cp <= 0xa4cf) || (cp >= 0xac00 && cp <= 0xd7a3) || (cp >= 0xff00 && cp <= 0xff60) || WIDE_BMP.has(cp)) w += 2
    else w += 1
  }
  return w
}
const WIDE_BMP = new Set([0x231a, 0x231b, 0x23e9, 0x23ea, 0x23eb, 0x23ec, 0x23f0, 0x23f3, 0x2614, 0x2615, 0x26a1, 0x2705, 0x270a, 0x270b, 0x2728, 0x274c, 0x2753, 0x2754, 0x2755, 0x2757, 0x2b50, 0x2b55])
export const lineWidth = (line: Line): number => displayWidth(plain(line))

/** Drop whole trailing parts until the line fits `columns`; a lone part is kept (the surface truncates it). */
export function fit(line: Line, columns: number): Line {
  const parts: Line[] = [[]]
  for (const r of line) {
    if (r === SEPARATOR) parts.push([])
    else parts[parts.length - 1]?.push(r)
  }
  while (parts.length > 1 && lineWidth(parts.flatMap((p, k) => (k === 0 ? p : [SEPARATOR, ...p]))) > columns) parts.pop()
  return parts.flatMap((p, k) => (k === 0 ? p : [SEPARATOR, ...p]))
}
