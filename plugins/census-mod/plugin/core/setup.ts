// /census-setup: the questions, what an answer means, and the settings.json surgery. Pure: no `$`.
import { DEFAULT_SEGMENTS } from './render'

export type RecordMode = 'yes' | 'shadow' | 'no'
export type Preset = 'two' | 'compact' | 'minimal'
export type Placement = 'above' | 'below'

/** What the person answered, in $.store. Absent = not answered; the defaults below apply. */
export type Saved = {
  offered?: boolean
  record?: RecordMode
  draw?: boolean
  placement?: Placement
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
  /** This census ships /census:vitals (vitals.py beside its cli.py, or its `census where` says so). */
  hasVitals: boolean
}

export const NO_DETECTION: Detection = { cliPath: null, version: null, statusLineCommand: null, ingestBlock: false, otherWriter: false, settingsInvalid: false, hasVitals: false }

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
export const commandIsCensus = (command: string): boolean =>
  /(^|[\s/\\'"])census(\.exe)?\s+(ingest|statusline)\b/.test(command) ||
  // Windows: `census install` points the status line at its launcher, `python "<census dir>\launcher.py" statusline`.
  /launcher\.py['"]?\s+(ingest|statusline)\b/.test(command)

/**
 * The files a status-line command runs, as absolute paths: `bash ~/.claude/line.sh`, `"$HOME/x.sh" --flag`,
 * `/abs/x`, and on Windows `powershell -File "C:\Users\u\my line.ps1"` (quoted, with spaces and backslashes).
 */
export function scriptCandidates(command: string, home: string | undefined, userProfile?: string): string[] {
  const out: string[] = []
  const root = home?.replace(/[\\/]+$/, '')
  const profile = (userProfile ?? home)?.replace(/[\\/]+$/, '') // %USERPROFILE% is its own variable
  for (const m of command.matchAll(/"([^"]*)"|'([^']*)'|(\S+)/g)) {
    const t = m[1] ?? m[2] ?? m[3] ?? ''
    let p = t
    if (root && (t === '~' || /^~[\\/]/.test(t))) p = root + t.slice(1)
    else if (profile && /^%USERPROFILE%[\\/]/.test(t)) p = profile + t.slice(t.search(/[\\/]/))
    else if (root && /^(\$HOME|\$\{HOME\})[\\/]/.test(t)) p = root + t.slice(t.search(/[\\/]/))
    if ((p.startsWith('/') || /^[A-Za-z]:[\\/]/.test(p) || p.startsWith('\\\\')) && !out.includes(p)) out.push(p)
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

export type SetupEnv = { CENSUS_MOD_STORE?: string; CENSUS_STATUSLINE_SEGMENTS?: string; CENSUS_MOD_PLACEMENT?: string; HOME?: string }
export type Effective = { record: RecordMode; shadowDir: string | null; draw: boolean; placement: Placement; segments: string | undefined; pr: boolean }

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
    // An install that never answered stays where it was (above); the question recommends below for new ones.
    placement: ((p: string | undefined): Placement | null => (p === 'above' || p === 'below' ? p : null))(env.CENSUS_MOD_PLACEMENT?.trim().toLowerCase()) ?? saved.placement ?? 'above',
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
  recReplace: 'Replace my status line — census-mod records and draws it',
  recYes: 'Yes — record into census (dashboards, vitals and liveness use it)',
  recShadow: "Shadow — record into a separate store to compare; dashboards won't see it",
  recNo: "No — don't record (dashboards and vitals won't see this account)",
  recNoFed: 'No — leave recording to my status line (it keeps feeding census)',
  recNoOther: "No — don't record (whatever else writes keeps feeding census)",
  drawBelow: "Yes — below the input, under Claude Code's hint line",
  drawAbove: 'Yes — above the input, in the band',
  drawNo: 'No — record only, draw nothing',
  wRemove: "Remove this account's status line (census-mod draws it instead)",
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
    question: 'census-mod is installed. Set it up now? It takes a few questions: whether to record sessions into census, whether and where to draw the status line, and which layout.',
    options: [rec(L.offerYes, true), L.offerLater],
  }),
  old: (version: string): Question => ({
    header: '📝 Census',
    question: `The census plugin here is ${version}; census-mod needs ${MIN_CENSUS} or newer to tell a live session from a gone one. Record anyway?`,
    options: [rec(L.oldNo, true), L.oldYes],
  }),
  /**
   * Almost nobody else records into census, so the common path is Yes or No. Shadow (a separate store to compare
   * in) and Replace (swap a status line that feeds census for census-mod) are offered only where something already
   * records into the real store.
   */
  record: (det: Detection, shadowByEnv = false): Question => {
    const readers = det.hasVitals ? 'the overseer dashboard, /census:vitals and session liveness' : 'the overseer dashboard and session liveness'
    const OVERSEER = det.hasVitals ? 'the overseer dashboard, /census:vitals and liveness' : 'the overseer dashboard and liveness'
    if (det.ingestBlock && shadowByEnv) {
      return {
        header: '📝 Record',
        question: `CENSUS_MOD_STORE is set, so census-mod records into a separate shadow store whatever you answer, and your status line — which records this account's sessions into census, the store ${OVERSEER} read — stays as that store's writer. Unset it and run /census-setup again to replace the status line. Compare in the shadow store, or leave recording to your status line?`,
        options: [rec(L.recShadow, true), L.recYes, L.recNoFed],
      }
    }
    if (det.ingestBlock) {
      return {
        header: '📝 Record',
        question: `Your status line already records this account's sessions into census — the store ${OVERSEER} read. Replace it with census-mod (records and draws the line; yours is backed up), compare first, or leave recording to your status line (it keeps feeding census)?`,
        options: [rec(L.recReplace, true), L.recShadow, L.recYes, L.recNoFed],
      }
    }
    if (det.otherWriter) {
      return {
        header: '📝 Record',
        question: `Something has been recording this account's sessions into census in the last few minutes — the store ${OVERSEER} read. Two writers on one store muddle liveness: compare first in a separate store, or record anyway?`,
        options: [rec(L.recShadow, true), L.recYes, L.recNoOther],
      }
    }
    return {
      header: '📝 Record',
      question: `Record this account's sessions into census? That's what ${readers} read (context, cost, limits, git, PR) — without it they see nothing from this account.`,
      options: [rec(L.recYes, true), L.recNo],
    }
  },
  place: (): Question => ({
    header: '🎛️ Draw',
    question: 'Where should census-mod draw your status line?',
    options: [rec(L.drawBelow, true), L.drawAbove],
  }),
  draw: (): Question => ({
    header: '🎛️ Draw',
    question: 'Should census-mod draw your status line, and where?',
    options: [rec(L.drawBelow, true), L.drawAbove, L.drawNo],
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
  if (is(answer, L.recYes) || is(answer, L.recReplace)) return 'yes'
  if (is(answer, L.recShadow)) return 'shadow'
  if (is(answer, L.recNo) || is(answer, L.recNoFed) || is(answer, L.recNoOther)) return 'no'
  return null
}
/** The record answer that also hands the status line over to census-mod. */
export const replaceFrom = (answer: string): boolean => is(answer, L.recReplace)
/** The draw answer as a placement; null means "don't draw". */
export function placementFrom(answer: string): Placement | null {
  if (is(answer, L.drawAbove)) return 'above'
  if (is(answer, L.drawBelow)) return 'below'
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
    const parsed: unknown = backupText === null ? null : JSON.parse(backupText)
    // A scalar, an array or null is not a backup: nothing to put back.
    backup = parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? (parsed as { statusLine?: unknown }) : null
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

/** `census where` JSON to "does this census ship vitals"; anything unreadable (an older census, a failure) is no. */
export function vitalsFromWhere(stdout: string): boolean {
  try {
    return (JSON.parse(stdout) as { vitals?: unknown }).vitals === true
  } catch {
    return false
  }
}

/** A CLI that is a Python script has its plugin's scripts beside it; anything else (a launcher on PATH) is asked. */
export const isPythonCli = (cliPath: string): boolean => cliPath.endsWith('.py')
