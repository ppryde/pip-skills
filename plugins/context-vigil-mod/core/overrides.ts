import type { Override, OverrideValues } from '../types'

// Threshold overrides keyed by model, window or both, in a hand-editable overrides.json.
// Each value comes from the most specific matching override that sets it, field by field; the
// account settings sit beneath them all.
//
//   { model: 'opus5.5', window: 1M }  >  { model: 'opus', window: 1M }  >  { window: 1M }
//   >  { model: 'opus5.5' }  >  { model: 'opus' }  >  settings

export const VALUE_KEYS = ['nudgeAt', 'step', 'lastLightAt'] as const
type ValueKey = typeof VALUE_KEYS[number]

export const DEFAULT_OVERRIDES: Override[] = [{ window: 200_000, nudgeAt: 70 }]

// 'claude-opus-5-5[1m]', 'Opus 5.5 (1M context)' and 'opus5.5' all lead with opus·5·5.
export function modelTokens(model: string): string[] {
  const t = model.toLowerCase().match(/[a-z]+|\d+/g) ?? []
  return t[0] === 'claude' ? t.slice(1) : t
}

// A pattern is a family and at most a major.minor version: 'opus', 'opus5', 'opus5.5'.
export function validPattern(pattern: string): boolean {
  const t = modelTokens(pattern)
  return t.length >= 1 && t.length <= 3 && /^[a-z]+$/.test(t[0]!) && t.slice(1).every(x => /^\d+$/.test(x))
}

// The pattern naming a model's version: 'claude-haiku-4-5-20251001' → 'haiku4.5'.
export function patternFor(model: string): string | null {
  const t = modelTokens(model)
  if (!t[0] || !/^[a-z]+$/.test(t[0])) return null
  const nums: string[] = []
  for (const x of t.slice(1)) { if (!/^\d+$/.test(x) || x.length > 2 || nums.length === 2) break; nums.push(x) }
  return t[0] + nums.join('.')
}

export function modelMatches(pattern: string, model: string): boolean {
  const p = modelTokens(pattern)
  const m = modelTokens(model)
  return p.length > 0 && p.length <= m.length && p.every((x, i) => x === m[i])
}

// Both keys beat one; of one, window beats model; between models, the longer pattern wins.
function specificity(r: Override): number {
  const tier = r.model !== undefined && r.window !== undefined ? 3 : r.window !== undefined ? 2 : 1
  return tier * 1_000 + (r.model === undefined ? 0 : modelTokens(r.model).length)
}

const matches = (r: Override, model: string | null, window: number | null): boolean =>
  (r.model === undefined || (model !== null && modelMatches(r.model, model)))
  && (r.window === undefined || r.window === window)

export type Ambiguity = { model: Override; window: Override; fields: ValueKey[] }

export type Resolved = {
  values: OverrideValues
  from: Partial<Record<ValueKey, Override>>
  // A window-only and a model-only override both set a field and nothing with both keys settles it.
  ambiguous: Ambiguity | null
}

export function resolve(base: OverrideValues, overrides: Override[], model: string | null, window: number | null): Resolved {
  const hits = ordered(overrides.filter(r => matches(r, model, window)))
  const values: OverrideValues = { ...base }
  const from: Partial<Record<ValueKey, Override>> = {}
  for (const k of VALUE_KEYS) {
    const r = hits.find(h => h[k] !== undefined)
    if (r) { values[k] = r[k]!; from[k] = r }
  }
  const byWindow = hits.find(h => h.model === undefined)
  const modelOnly = hits.filter(h => h.window === undefined)
  const fields = byWindow ? VALUE_KEYS.filter(k => from[k] === byWindow && modelOnly.some(h => h[k] !== undefined)) : []
  const byModel = modelOnly.find(h => fields.some(k => h[k] !== undefined))
  return { values, from, ambiguous: byWindow && byModel ? { model: byModel, window: byWindow, fields } : null }
}

export function ordered(overrides: Override[]): Override[] {
  return [...overrides].sort((a, b) => specificity(b) - specificity(a))
}

const keyOf = (r: Pick<Override, 'model' | 'window'>): string =>
  `${r.model === undefined ? '*' : modelTokens(r.model).join('.')}@${r.window ?? '*'}`

export const sameKey = (a: Pick<Override, 'model' | 'window'>, b: Pick<Override, 'model' | 'window'>): boolean => keyOf(a) === keyOf(b)

// Adding an override replaces the one with the same key.
export function setOverride(overrides: Override[], override: Override): Override[] {
  return [...overrides.filter(r => !sameKey(r, override)), override]
}

export function removeOverride(overrides: Override[], key: Pick<Override, 'model' | 'window'>): { overrides: Override[]; removed: boolean } {
  const next = overrides.filter(r => !sameKey(r, key))
  return { overrides: next, removed: next.length !== overrides.length }
}

// '1m', '1M', '200k', '1000000' → tokens.
export function parseWindow(s: string): number | null {
  const m = /^(\d+(?:\.\d+)?)([km]?)$/i.exec(s.trim())
  if (!m) return null
  const unit = m[2]?.toLowerCase()
  const scaled = Number(m[1]) * (unit === 'k' ? 1_000 : unit === 'm' ? 1_000_000 : 1)
  // Only float noise is rounded (1.1m); a count that is not whole (1.4, 1.0005k) is refused, so
  // `rm window=1.4` can never take out window=1.
  const n = Math.round(scaled)
  return Math.abs(scaled - n) < 1e-6 && n > 0 ? n : null
}

export function formatWindow(n: number): string {
  return n % 1_000_000 === 0 ? `${n / 1_000_000}M` : n % 1_000 === 0 ? `${n / 1_000}k` : `${n}`
}

export function formatKey(r: Pick<Override, 'model' | 'window'>): string {
  return [r.model !== undefined ? `model=${r.model}` : '', r.window !== undefined ? `window=${formatWindow(r.window)}` : ''].filter(Boolean).join(' ')
}

const LABEL: Record<ValueKey, string> = { nudgeAt: 'nudge', step: 'step', lastLightAt: 'last light' }

export function formatOverride(r: Override): string {
  return `${formatKey(r)} → ${VALUE_KEYS.filter(k => r[k] !== undefined).map(k => `${LABEL[k]} ${r[k]}%`).join(', ')}`
}

// overrides.json: { "overrides": [ ... ] }. A fault drops only the override it is in; each is named for the person.
// A file that cannot be read as a list at all (`fileFault`) names no override: the caller keeps what it had.
export type Checked = { overrides: Override[]; faults: string[]; fileFault?: true }

const KEYS = new Set<string>(['model', 'window', ...VALUE_KEYS])
const isPct = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v) && v >= 1 && v <= 100

export function checkOverrides(text: string): Checked {
  let raw: unknown
  try { raw = JSON.parse(text) } catch (err) { return { overrides: [], faults: [`not valid JSON (${String((err as Error).message).slice(0, 80)})`], fileFault: true } }
  const list = (raw as { overrides?: unknown } | null)?.overrides
  if (!raw || typeof raw !== 'object' || !Array.isArray(list)) return { overrides: [], faults: ['expected { "overrides": [ … ] }'], fileFault: true }
  const overrides: Override[] = []
  const faults: string[] = []
  list.forEach((v, i) => {
    const at = `override ${i + 1}`
    if (!v || typeof v !== 'object' || Array.isArray(v)) { faults.push(`${at}: not an object`); return }
    const o = v as Record<string, unknown>
    const unknown = Object.keys(o).filter(k => !KEYS.has(k))
    if (unknown.length) { faults.push(`${at}: unknown key ${unknown.map(k => `"${k}"`).join(', ')} (allowed: ${[...KEYS].join(', ')})`); return }
    if (o.model !== undefined && (typeof o.model !== 'string' || !validPattern(o.model))) { faults.push(`${at}: model must be a family and optional version, like "opus" or "opus5.5"`); return }
    if (o.window !== undefined && !(typeof o.window === 'number' && Number.isInteger(o.window) && o.window > 0)) { faults.push(`${at}: window must be a whole number of tokens, like 1000000`); return }
    if (o.model === undefined && o.window === undefined) { faults.push(`${at}: needs a model, a window or both`); return }
    for (const k of ['nudgeAt', 'lastLightAt'] as const) if (o[k] !== undefined && !isPct(o[k])) { faults.push(`${at}: ${k} must be a whole % from 1 to 100`); return }
    if (o.step !== undefined && !(typeof o.step === 'number' && Number.isInteger(o.step) && o.step >= 1 && o.step <= 50)) { faults.push(`${at}: step must be a whole % from 1 to 50`); return }
    if (!VALUE_KEYS.some(k => o[k] !== undefined)) { faults.push(`${at}: sets nothing (give it ${VALUE_KEYS.join(', ')} or any of them)`); return }
    const r = o as Override
    const dup = overrides.findIndex(x => sameKey(x, r))
    if (dup !== -1) { faults.push(`${at}: same key as an earlier override (${formatKey(r)}); the earlier one stands`); return }
    overrides.push(r)
  })
  return { overrides, faults }
}

export function overridesJson(overrides: Override[]): string {
  return `${JSON.stringify({ overrides }, null, 2)}\n`
}

// 0.1.3 kept per-model overrides in the settings store (`modelThresholds`, substring patterns such
// as `opus` or `[1m]`). They move into overrides.json once: `[1m]` becomes window=1M, the rest a
// model pattern. One that does not fit this format is named in `dropped`, with why. Entries go in
// 0.1.3's own order (longest pattern first, then by name), so when two collapse to one key
// (`claude-opus`, `opus`) the one that used to win is the one kept.
export function fromModelThresholds(raw: unknown): { overrides: Override[]; dropped: string[] } {
  const table = (raw as { modelThresholds?: unknown } | null)?.modelThresholds
  const out: Override[] = []
  const dropped: string[] = []
  if (!table || typeof table !== 'object' || Array.isArray(table)) return { overrides: out, dropped }
  const entries = Object.entries(table as Record<string, unknown>)
    .sort(([a], [b]) => b.length - a.length || (a < b ? -1 : a > b ? 1 : 0))
  for (const [key, v] of entries) {
    const o = (v && typeof v === 'object' ? v : {}) as Record<string, unknown>
    const lower = key.trim().toLowerCase()
    const window = lower.includes('[1m]') ? 1_000_000 : undefined
    const rest = lower.replace('[1m]', '').replace(/^[-\s]+|[-\s]+$/g, '')
    const tokens = modelTokens(rest)
    const model = rest ? (validPattern(rest) ? tokens[0]! + tokens.slice(1).join('.') : null) : undefined
    const values = { ...(isPct(o.nudgeAt) ? { nudgeAt: o.nudgeAt } : {}), ...(isPct(o.lastLightAt) ? { lastLightAt: o.lastLightAt } : {}) }
    if (model === null || (model === undefined && window === undefined)) { dropped.push(`${key} (no equivalent)`); continue }
    if (!Object.keys(values).length) { dropped.push(`${key} (sets nothing)`); continue }
    const r: Override = { ...(model !== undefined ? { model } : {}), ...(window !== undefined ? { window } : {}), ...values }
    const winner = out.find(x => sameKey(x, r))
    if (winner) { dropped.push(`${key} (${formatKey(winner)} from a longer pattern won)`); continue }
    out.push(r)
  }
  return { overrides: out, dropped }
}

// /vigil-overrides · /vigil-overrides add · /vigil-overrides rm [model=<m>] [window=<w>]
export type OverridesCommand =
  | { op: 'list' }
  | { op: 'add' }
  | { op: 'rm'; key: Pick<Override, 'model' | 'window'> }
  | { op: 'error' }

export function parseOverridesArgs(args: string): OverridesCommand {
  const words = args.trim().split(/\s+/).filter(Boolean)
  if (words.length === 0 || (words.length === 1 && (words[0] === 'list' || words[0] === 'check'))) return { op: 'list' }
  if (words.length === 1 && words[0] === 'add') return { op: 'add' }
  if (words[0] !== 'rm') return { op: 'error' }
  const key = parseKey(words.slice(1).join(' '))
  return key ? { op: 'rm', key } : { op: 'error' }
}

// 'model=opus5.5 window=1m' (either or both) → an override key; null when it names neither or is malformed.
export function parseKey(text: string): Pick<Override, 'model' | 'window'> | null {
  let model: string | undefined
  let window: number | undefined
  for (const w of text.trim().split(/\s+/).filter(Boolean)) {
    const eq = w.indexOf('=')
    const k = eq > 0 ? w.slice(0, eq).toLowerCase() : ''
    const v = w.slice(eq + 1)
    if (k === 'model' && model === undefined && validPattern(v)) { model = v; continue }
    const n = k === 'window' && window === undefined ? parseWindow(v) : null
    if (n !== null) { window = n; continue }
    return null
  }
  if (model === undefined && window === undefined) return null
  return { ...(model !== undefined ? { model } : {}), ...(window !== undefined ? { window } : {}) }
}

// The /vigil-overrides add dialog: questions, like setup's, are not notices and carry no emoji.
export const ASK = {
  key: 'Which sessions should this override cover? (Other: model=… window=…, either or both)',
  nudge: (key: string) => `For ${key}: at what % of context should I suggest a handover?`,
  step: 'Then nudge again every how many %?',
  lastLight: 'Last light: only write its handover from what % of context?',
}
