import type { Fields, Pending, PendingReason, Settings, Snapshot } from '../types'
import { TOOL_FULL } from './name'

export function nextThreshold(pct: number, s: Pick<Settings, 'nudgeAt' | 'step'>, lastNudged: number | null): number | null {
  if (pct < s.nudgeAt) return null
  const crossed = s.nudgeAt + Math.floor((pct - s.nudgeAt) / s.step) * s.step
  if (lastNudged !== null && crossed <= lastNudged) return null
  return crossed
}

// An unattended (auto-mode) handover waits until context has grown at least one step above the
// session's baseline (its first reading), so a session that starts just under the threshold
// cannot hand over, clear and hand over again within a turn. Attended nudges ignore this.
export function grownEnough(pct: number, baseline: number | null, step: number): boolean {
  return baseline !== null && pct - baseline >= step
}

// The turn that wrote a handover ends just after the tool call; a turn ending later than this
// means the conversation moved on and the handover is stale.
export const REUSE_SLACK_MS = 60_000

// Is a handover still the latest word on the session? No turn has completed since it was written
// (give or take the slack). A process that has seen no turn yet (a restart, a --resume) knows only
// the clock: the handover must be young. One rule for reuse (R1-04) and for a manual /clear's
// automatic resume (R1-10).
export function fresh(p: Pick<Pending, 'createdAt'>, lastApiAt: number | null, now: number): boolean {
  return (lastApiAt ?? now) <= p.createdAt + REUSE_SLACK_MS
}

// A pending handover is reused (cleared into) only when it was written for a clear and is fresh;
// anything else gets a fresh handover.
export function reusable(p: Pick<Pending, 'reason' | 'createdAt'> | null, lastApiAt: number | null, now: number): boolean {
  if (!p || (p.reason !== 'threshold' && p.reason !== 'request')) return false
  return fresh(p, lastApiAt, now)
}

export const FIELD_NAMES = ['goal', 'state', 'decisions', 'next_step', 'open_questions', 'failed_attempts', 'session_name'] as const
const REQUIRED = ['goal', 'state', 'next_step', 'session_name'] as const

const DESCRIBE: Record<(typeof FIELD_NAMES)[number], string> = {
  goal: 'What this session is trying to achieve, in a sentence or two.',
  state: 'Where the work stands right now: done, in flight, blocked.',
  decisions: 'Decisions and rulings made, each with its reason.',
  next_step: 'The very next concrete action on resume.',
  open_questions: 'Questions still waiting on the person.',
  failed_attempts: 'Approaches tried that did not work, and why.',
  session_name: 'A short name for the session that resumes this work: 2–6 words saying what it will do next (e.g. "vigil-mod: shell handover flow"). It becomes the new session\'s name after the clear.',
}

export const INPUT_SCHEMA = {
  type: 'object',
  properties: Object.fromEntries(FIELD_NAMES.map(n => [n, { type: 'string', description: DESCRIBE[n] }])),
  required: [...REQUIRED],
} as const

export const TOOL_DESCRIPTION =
  'Save a handover for this session so work can resume after the context is cleared. ' +
  'Call it when context-vigil-mod asks you to, or when the person asks you for a handover. Never write a handover any other way: no ad-hoc files or summaries. ' +
  'Write for a fresh reader who knows nothing of this conversation.'

export function cleanName(raw: string): string {
  return raw.replace(/\s+/g, ' ').trim().replace(/^\/+/, '').slice(0, 60).trim()
}

export function parseFields(input: Record<string, unknown>): { ok: true; fields: Fields } | { ok: false; error: string } {
  const out: Record<string, string> = {}
  for (const name of FIELD_NAMES) {
    const v = input[name]
    if (v === undefined || v === null) { out[name] = ''; continue }
    if (typeof v !== 'string') return { ok: false, error: `${name} must be a string` }
    out[name] = name === 'session_name' ? cleanName(v) : v.trim()
  }
  for (const name of REQUIRED) if (!out[name]) return { ok: false, error: `${name} is required and must not be blank` }
  return { ok: true, fields: out as Fields }
}

const TITLES: Record<(typeof FIELD_NAMES)[number], string> = {
  goal: 'Goal', state: 'State', decisions: 'Decisions', next_step: 'Next step',
  open_questions: 'Open questions', failed_attempts: 'Failed attempts', session_name: 'Session name',
}

export function renderHandover(f: Fields, s: Snapshot): string {
  const parts = [`# 📜 Handover — ${s.session} (${s.at})`, `**Next session:** ${f.session_name}`, '']
  for (const name of FIELD_NAMES) {
    if (name === 'session_name' || !f[name]) continue
    parts.push(`## ${TITLES[name]}`, '', f[name], '')
  }
  parts.push('## Snapshot', '',
    `- cwd: ${s.cwd}`,
    `- branch: ${s.branch ?? '(not a git repo)'}`,
    `- context: ${s.contextPct === null ? 'unknown' : `${s.contextPct}%`}`,
    `- dirty: ${s.dirty.length ? s.dirty.join(', ') : 'none'}`,
    `- edited this session: ${s.edited.length ? s.edited.join(', ') : 'none'}`,
    '')
  return parts.join('\n')
}

const WHY: Record<PendingReason, string> = {
  threshold: 'Context is past the handover threshold.',
  request: 'The person asked for a handover.',
  last_light: 'The session has gone idle and the prompt cache is about to go cold. Do not clear; just save the handover.',
  limit: 'A usage limit is close. Save the handover so work can resume after the reset.',
}

export function instructionText(reason: PendingReason): string {
  return `[context-vigil-mod] ${WHY[reason]} Call the ${TOOL_FULL} tool now with a complete handover ` +
    '(goal, state, decisions, next step, open questions, failed attempts, session name). Do nothing else this turn.'
}

export function resumeText(path: string): string {
  return `[context-vigil-mod] Resume from the handover injected above (saved at ${path}). Start with its next step.`
}

export function injectText(markdown: string): string {
  return `[context-vigil-mod] Handover from before the clear:\n\n${markdown}`
}

// After a limit early stop there was no clear: the conversation is still here.
export function limitResumeText(path: string | null): string {
  if (path === null) {
    return '[context-vigil-mod] The usage limit has reset. No handover was written before the stop (it was deferred or classic was active); pick up from the conversation as it stands.'
  }
  return `[context-vigil-mod] The usage limit has reset. Continue the work; the handover you wrote is saved at ${path} if you need it.`
}

// Any mention of a handover at all: the looser net behind the tool (a person who said "handover" and
// then had the model call the tool meant it).
export function mentionsHandover(text: string): boolean {
  return /hand[ -]?over|hand(?:ing)?[ -]?off/i.test(text)
}

const REQUEST_MAX_WORDS = 12
const REQUEST_CORE = /\bhand[ -]?over\b|\bhand(?:ing)?[ -]?off\b|\bhand\s+(?:this|it|that|things|everything|us|work|session|this session)\s+(?:over|off)\b|\bhand\s+this\s+session\s+(?:over|off)\b/
const REQUEST_NEGATION = /\b(?:don'?t|do not|dont|never|no|not|stop|cancel|without|skip|instead|isn'?t|won'?t|can'?t)\b/
// Questions about handovers, and talk about the mod's code, files and behaviour.
const REQUEST_ABOUT = /\b(?:how|what|what'?s|whats|why|when|where|which|who|does|did|is|are|was|were|has|have|bug|bugs|fix|fixing|fixed|broken|broke|fail|fails|failed|failing|wrong|work|works|working|implement|code|file|files|test|tests|spec|docs?|document|explain|show|read|review|check|debug|issue|error|last|previous|latest|update|improve|refactor|think|tool|mod|hook|slow|empty|status|summary|details?|info|information|list|history|log|logs|count|size|path|location|contents?|diff|name)\b/
const REQUEST_CONDITION = /\b(?:if|unless|after|before|once|whenever|until)\b/
const REQUEST_LEAD = new Set([
  'handover', 'handoff', 'hand', 'do', 'run', 'start', 'begin', 'make', 'write', 'create', 'give', 'trigger', 'initiate', 'time', "let's", 'lets', 'let',
  'go', 'ok', 'okay', 'alright', 'right', 'so', 'now', 'please', 'pls', 'can', 'could', 'would', 'will', 'shall', 'i', 'we', "it's", 'its', 'ready',
  'need', 'needs', 'want', 'yes', 'yep', 'yeah', 'sure', 'just', 'then', 'kindly', 'hey', 'hi',
])

/** Is this short human message a request to hand over now (not a question or talk about handovers)? */
export function isHandoverRequest(text: string): boolean {
  const clean = text.toLowerCase().replace(/[.!?,;:-]+/g, ' ').replace(/\s+/g, ' ').trim()
  if (!clean || clean.startsWith('/')) return false
  const words = clean.split(' ')
  if (words.length > REQUEST_MAX_WORDS) return false
  if (!REQUEST_CORE.test(clean)) return false
  if (REQUEST_NEGATION.test(clean) || REQUEST_ABOUT.test(clean) || REQUEST_CONDITION.test(clean)) return false
  return REQUEST_LEAD.has(words[0]!)
}
