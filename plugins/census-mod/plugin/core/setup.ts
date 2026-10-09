// /census-setup: the questions, what an answer means, and the settings.json surgery. Pure: no `$`.
import { DEFAULT_SEGMENTS } from './render'

export type RecordMode = 'yes' | 'shadow' | 'no'
export type Preset = 'two' | 'compact' | 'minimal'

/** What the person answered, in $.store. Absent = not answered; the defaults below apply. */
export type Saved = {
  offered?: boolean
  record?: RecordMode
  draw?: boolean
  preset?: Preset
  pr?: boolean
  answeredAt?: number
}

export const SETUP_KEY = 'census-mod:setup'
export const MIN_CENSUS = '0.5.0'
export const BACKUP_FILE = 'census-mod.statusline.json'
export const SHADOW_DIRNAME = 'census-shadow'

export const PRESETS: Record<Preset, string> = {
  two: DEFAULT_SEGMENTS,
  compact: 'context,cache,limits,cost,model,git',
  minimal: 'context,limits/git',
}

// ---- what is on this machine ------------------------------------------------------------------

export type Detection = {
  cliPath: string | null
  /** From the census plugin's plugin.json beside the CLI; null when it cannot be told. */
  version: string | null
  /** This account's settings.json `statusLine.command`; null when there is none. */
  statusLineCommand: string | null
  /** Whether that command (or the script it runs) carries census's ingest block. */
  ingestBlock: boolean
  /** A census status-line writer touched the real store in the last few minutes. */
  otherWriter: boolean
  /** settings.json exists but is not valid JSON: it is never edited. */
  settingsInvalid: boolean
}

export const NO_DETECTION: Detection = { cliPath: null, version: null, statusLineCommand: null, ingestBlock: false, otherWriter: false, settingsInvalid: false }

export function versionParts(v: string): number[] {
  return v.split('.').map(p => (/^\d+$/.test(p) ? Number.parseInt(p, 10) : 0))
}
export function atLeast(version: string, min: string): boolean {
  const a = versionParts(version)
  const b = versionParts(min)
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const d = (a[i] ?? 0) - (b[i] ?? 0)
    if (d !== 0) return d > 0
  }
  return true
}

// Census's own sentinel (plugins/census/scripts/statusline.py START): the line that opens the block it adds.
export const INGEST_MARKER = '# --- census: record status-line payload'
export const hasIngestBlock = (text: string): boolean => text.includes(INGEST_MARKER)
/** A command that is itself census recording: `census ingest` or `census statusline`. */
export const commandIsCensus = (command: string): boolean => /(^|[\s/'"])census\s+(ingest|statusline)\b/.test(command)

/** The files a status-line command runs, as absolute paths: `bash ~/.claude/line.sh`, `"$HOME/x.sh" --flag`, `/abs/x`. */
export function scriptCandidates(command: string, home: string | undefined): string[] {
  const out: string[] = []
  for (const raw of command.split(/\s+/)) {
    const t = raw.replace(/^['"]+|['"]+$/g, '')
    let p = t
    if (home && (t === '~' || t.startsWith('~/'))) p = home.replace(/\/+$/, '') + t.slice(1)
    else if (home && (t.startsWith('$HOME/') || t.startsWith('${HOME}/'))) p = home.replace(/\/+$/, '') + t.slice(t.indexOf('/'))
    if (p.startsWith('/') && !out.includes(p)) out.push(p)
  }
  return out
}

export type Parsed = { ok: true; data: Record<string, unknown> } | { ok: false }
export function parseSettings(text: string): Parsed {
  try {
    const data = JSON.parse(text) as unknown
    return data && typeof data === 'object' && !Array.isArray(data) ? { ok: true, data: data as Record<string, unknown> } : { ok: false }
  } catch {
    return { ok: false }
  }
}

export function statusLineCommand(data: Record<string, unknown>): string | null {
  const sl = data.statusLine as { command?: unknown } | undefined
  return sl && typeof sl === 'object' && typeof sl.command === 'string' ? sl.command : null
}

/** A census writer is active: a session entry written in the last `withinMs` that the mod did not write. */
export function writerActive(entries: { updatedAt: number; hasCensusMod: boolean }[], nowMs: number, withinMs = 180_000): boolean {
  return entries.some(e => !e.hasCensusMod && nowMs - e.updatedAt <= withinMs)
}

// ---- settings: env > $.store > defaults ----------------------------------------------------------

export type SetupEnv = { CENSUS_MOD_STORE?: string; CENSUS_STATUSLINE_SEGMENTS?: string; HOME?: string }
export type Effective = { record: RecordMode; shadowDir: string | null; draw: boolean; segments: string | undefined; pr: boolean }

/**
 * Before any answer: record to the real store ONLY if this account's status line does not carry the
 * census ingest block (else a second writer would share the store), draw yes, gh yes. An answer replaces
 * the default; an environment variable replaces both.
 */
export function effective(saved: Saved, env: SetupEnv, det: Detection, configRoot: string | null): Effective {
  const envShadow = env.CENSUS_MOD_STORE?.trim()
  const shadowAt = configRoot ? `${configRoot}/${SHADOW_DIRNAME}` : null
  let record: RecordMode = saved.record ?? (det.ingestBlock ? 'no' : 'yes')
  let shadowDir: string | null = record === 'shadow' ? shadowAt : null
  if (envShadow) {
    record = 'shadow'
    shadowDir = envShadow.startsWith('~/') && env.HOME ? env.HOME.replace(/\/+$/, '') + envShadow.slice(1) : envShadow
  }
  if (record === 'shadow' && !shadowDir) record = 'no' // nowhere to write
  const envSegments = env.CENSUS_STATUSLINE_SEGMENTS?.trim()
  return {
    record,
    shadowDir,
    draw: saved.draw ?? true,
    segments: envSegments || (saved.preset ? PRESETS[saved.preset] : undefined),
    pr: saved.pr ?? true,
  }
}

// ---- the questions (labels only; the recommendation rides in the label) -------------------------------

export type Question = { header: string; question: string; options: string[] }
const REC = ' (Recommended)'

export const L = {
  offerYes: 'Set it up now',
  offerLater: 'Not now — use the defaults',
  oldNo: "Don't record",
  oldYes: 'Record anyway',
  recYes: 'Yes — the real census store',
  recShadow: 'Shadow — a separate store, to compare first',
  recNo: 'No — do not record',
  drawYes: 'Yes',
  drawNo: 'No',
  wRemove: "Remove this account's status line (the band replaces it)",
  wKeep: "Keep my status line; census-mod won't record",
  wBoth: 'Keep both (not recommended)',
  presetTwo: 'Your two lines',
  presetCompact: 'Compact — one line',
  presetMinimal: 'Minimal — context, limits / git',
  prYes: 'Yes',
  prNo: "No — never call gh",
} as const

const rec = (s: string, on: boolean) => (on ? `${s}${REC}` : s)

export const Q = {
  offer: (): Question => ({
    header: '🧭 Setup',
    question: 'census-mod is installed. Set it up now? It takes a few questions: whether to record sessions into census, whether to draw the status-line band, and which layout.',
    options: [rec(L.offerYes, true), L.offerLater],
  }),
  old: (version: string): Question => ({
    header: '📝 Census',
    question: `The census plugin here is ${version}; census-mod needs ${MIN_CENSUS} or newer to tell a live session from a gone one. Record anyway?`,
    options: [rec(L.oldNo, true), L.oldYes],
  }),
  record: (det: Detection): Question => ({
    header: '📝 Record',
    question: det.ingestBlock
      ? "Record this account's sessions into census? Your status line already records into the real store, so Shadow (a separate store) is the safe way to compare."
      : "Record this account's sessions into the census store?",
    options: [rec(L.recYes, !det.ingestBlock), rec(L.recShadow, det.ingestBlock), L.recNo],
  }),
  draw: (): Question => ({
    header: '🎛️ Band',
    question: 'Draw the status line in the band above the prompt?',
    options: [rec(L.drawYes, true), L.drawNo],
  }),
  writers: (draw: boolean, otherWriter: boolean): Question => ({
    header: '⚠️ Writers',
    question: `This account's status line also records into the census store${otherWriter ? ' (and it has written in the last few minutes)' : ''}. Two writers on one store muddle idle and liveness. What now?`,
    options: draw ? [rec(L.wRemove, true), L.wKeep, L.wBoth] : [rec(L.wKeep, true), L.wBoth],
  }),
  preset: (): Question => ({
    header: '📐 Layout',
    question: 'Which segments in the band? (CENSUS_STATUSLINE_SEGMENTS still overrides this.)',
    options: [rec(L.presetTwo, true), L.presetCompact, L.presetMinimal],
  }),
  pr: (): Question => ({
    header: '🔀 PR',
    question: "Show the branch's open PR (number, review state) using gh? No means gh is never called.",
    options: [rec(L.prYes, true), L.prNo],
  }),
}

const strip = (label: string): string => label.replace(REC, '')
export const is = (answer: string, label: string): boolean => strip(answer) === label || strip(answer).trim() === label

export function recordFrom(answer: string): RecordMode | null {
  if (is(answer, L.recYes)) return 'yes'
  if (is(answer, L.recShadow)) return 'shadow'
  if (is(answer, L.recNo)) return 'no'
  return null
}
export function presetFrom(answer: string): Preset | null {
  if (is(answer, L.presetTwo)) return 'two'
  if (is(answer, L.presetCompact)) return 'compact'
  if (is(answer, L.presetMinimal)) return 'minimal'
  return null
}
export type Writers = 'remove' | 'keep' | 'both'
export function writersFrom(answer: string): Writers | null {
  if (is(answer, L.wRemove)) return 'remove'
  if (is(answer, L.wKeep)) return 'keep'
  if (is(answer, L.wBoth)) return 'both'
  return null
}
export const yes = (answer: string, label: string): boolean | null => (is(answer, label) ? true : null)

// ---- settings.json: remove the statusLine, back it up exactly, restore it ------------------------------

function indentOf(text: string): string | number {
  const m = /\n([ \t]+)"/.exec(text)
  return m ? (m[1] ?? 2) : 2
}
const serialise = (data: Record<string, unknown>, like: string): string => `${JSON.stringify(data, null, indentOf(like))}\n`

export type Removal = { ok: true; text: string; backup: string } | { ok: false; reason: 'invalid' | 'none' }

/** settings.json without its `statusLine`, every other key and its order kept; the backup holds the removed value verbatim. */
export function removeStatusLine(text: string, settingsPath: string, nowIso: string): Removal {
  const p = parseSettings(text)
  if (!p.ok) return { ok: false, reason: 'invalid' }
  if (!('statusLine' in p.data)) return { ok: false, reason: 'none' }
  const rest = Object.fromEntries(Object.entries(p.data).filter(([k]) => k !== 'statusLine'))
  return { ok: true, text: serialise(rest, text), backup: `${JSON.stringify({ statusLine: p.data.statusLine, removedAt: nowIso, from: settingsPath }, null, 2)}\n` }
}

export type Restoration =
  | { done: 'restored'; text: string }
  | { done: 'already' }
  | { done: 'kept'; why: 'present' | 'invalid' | 'no-backup' }

const same = (a: unknown, b: unknown): boolean => JSON.stringify(a) === JSON.stringify(b)

/** Put the backed-up statusLine back, but only into a settings.json that has none (or already has exactly it). */
export function restoreStatusLine(text: string, backupText: string | null): Restoration {
  let backup: { statusLine?: unknown } | null = null
  try {
    backup = backupText === null ? null : (JSON.parse(backupText) as { statusLine?: unknown })
  } catch {
    backup = null
  }
  if (!backup || !('statusLine' in backup)) return { done: 'kept', why: 'no-backup' }
  const p = parseSettings(text)
  if (!p.ok) return { done: 'kept', why: 'invalid' }
  if ('statusLine' in p.data) return same(p.data.statusLine, backup.statusLine) ? { done: 'already' } : { done: 'kept', why: 'present' }
  return { done: 'restored', text: serialise({ ...p.data, statusLine: backup.statusLine }, text) }
}

export const settingsTmp = (path: string): string => `${path}.census-mod.tmp`

/** An existing backup holding a DIFFERENT status line than the one about to be removed: keep it, refuse the removal. */
export function backupBlocks(existing: string | null, newBackup: string): boolean {
  const statusOf = (t: string): unknown => {
    try {
      return (JSON.parse(t) as { statusLine?: unknown }).statusLine
    } catch {
      return undefined
    }
  }
  if (existing === null) return false
  const old = statusOf(existing)
  return old !== undefined && !same(old, statusOf(newBackup))
}
