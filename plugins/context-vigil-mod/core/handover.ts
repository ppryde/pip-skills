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

// A pending handover is reused (cleared into) only when it was written for a clear and no
// turn has completed since; anything else gets a fresh handover.
export function reusable(p: Pick<Pending, 'reason' | 'createdAt'> | null, lastApiAt: number | null): boolean {
  if (!p || (p.reason !== 'threshold' && p.reason !== 'request')) return false
  return lastApiAt === null || lastApiAt <= p.createdAt + REUSE_SLACK_MS
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
  'Call it only when context-vigil-mod asks you to. Write for a fresh reader who knows nothing of this conversation.'

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
export function limitResumeText(path: string): string {
  return `[context-vigil-mod] The usage limit has reset. Continue the work; the handover you wrote is saved at ${path} if you need it.`
}
