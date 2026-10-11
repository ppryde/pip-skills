// PR state learned from mod events, never from GitHub (WF-269). Pure: no `$`.
//
// What the engine gives a mod in a local session (proved live, see the field notes): the Bash tool result carries
// `gitOperation` for commits, pushes and PR-changing `gh` commands (created, ready, draft, closed, merged,
// reopened, commented, edited, auto-merge), and nothing for `gh pr view` or checkout. The status-line payload's `pr`
// is not readable by a mod, and a local session gets no GitHub `session.receive`. So a record is kept per
// repo+branch from those operations, newest `at` winning, and a field an event lacks keeps its old value.
import type { Pr } from './types'

export type PrAction = 'created' | 'edited' | 'merged' | 'commented' | 'closed' | 'reopened' | 'ready' | 'draft' | 'auto-merge-enabled' | 'auto-merge-disabled'
export type GitOperation = { push?: { branch: string }; pr?: { number: number; url?: string; action: string } }
export type PrState = 'open' | 'closed' | 'merged'

export type PrRecord = {
  number: number
  url?: string
  state: PrState
  review?: string
  lastAction: string
  /** Where the newest word came from: a tool event, or the opt-in `gh` lookup. */
  source: 'event' | 'gh'
  /** `$.clock.now()` ms of that word. */
  at: number
  /** A push since: the review state may have moved, so it draws dimmed until something confirms it. */
  stale?: boolean
  sessionId: string
  worktree: string
}

/** Drawn dimmed after this long with nothing confirming it. */
export const DIM_AFTER_MS = 24 * 3600_000

const ACTIONS: ReadonlySet<string> = new Set(['created', 'edited', 'merged', 'commented', 'closed', 'reopened', 'ready', 'draft', 'auto-merge-enabled', 'auto-merge-disabled'])

/** `owner/name` from an origin URL (https, ssh or scp-like); null for anything that is not a plain two-part path. */
export function repoOf(url: string): string | null {
  const m = url.trim().match(/^(?:[a-z+]+:\/\/(?:[^@/]+@)?[^/:]+(?::\d+)?\/|[^@\s]+@[^:\s]+:)([^/\s]+)\/([^/\s]+?)(?:\.git)?\/?$/i)
  return m ? `${m[1]}/${m[2]}` : null
}

export const prKey = (repo: string, branch: string): string => `pr:${repo}#${branch}`
export const prPrefix = (repo: string): string => `pr:${repo}#`

/** The `gitOperation` block of a Bash tool result, or null when the result has none (or is not a Bash result). */
export function gitOperationOf(result: unknown): GitOperation | null {
  if (typeof result !== 'object' || result === null) return null
  const op = (result as { gitOperation?: unknown }).gitOperation
  if (typeof op !== 'object' || op === null) return null
  const out: GitOperation = {}
  const push = (op as { push?: { branch?: unknown } }).push
  if (push && typeof push.branch === 'string' && push.branch) out.push = { branch: push.branch }
  const pr = (op as { pr?: { number?: unknown; url?: unknown; action?: unknown } }).pr
  if (pr && typeof pr.number === 'number' && Number.isInteger(pr.number) && pr.number > 0 && typeof pr.action === 'string' && ACTIONS.has(pr.action)) {
    out.pr = { number: pr.number, action: pr.action, ...(typeof pr.url === 'string' && pr.url ? { url: pr.url } : {}) }
  }

  return out.push || out.pr ? out : null
}

/** What a PR action changes: only the fields it speaks about. */
/** `review: null` clears the review state (gh says the PR needs none). */
export type Patch = { number: number; url?: string; state?: PrState; review?: string | null; lastAction: string }

/**
 * The patch for one `gitOperation.pr`. `draftFlag`: the command passed --draft. Actions that only touch the PR
 * (comment, edit, auto-merge) change nothing but the time and the action.
 */
export function patchFor(pr: NonNullable<GitOperation['pr']>, draftFlag: boolean): Patch {
  const base: Patch = { number: pr.number, lastAction: pr.action, ...(pr.url ? { url: pr.url } : {}) }
  switch (pr.action) {
    case 'created': return { ...base, state: 'open', ...(draftFlag ? { review: 'draft' } : {}) }
    case 'ready': return { ...base, state: 'open', review: 'pending' }
    case 'draft': return { ...base, state: 'open', review: 'draft' }
    case 'reopened': return { ...base, state: 'open' }
    case 'closed': return { ...base, state: 'closed' }
    case 'merged': return { ...base, state: 'merged' }
    default: return base
  }
}

/** Newest `at` wins; a field the patch lacks keeps its old value; a different PR number replaces the record. */
export function applyPatch(old: PrRecord | undefined, patch: Patch, at: number, ctx: { sessionId: string; worktree: string; source?: 'event' | 'gh' }): PrRecord | undefined {
  if (old && old.number === patch.number && at < old.at) return old
  const keep = old && old.number === patch.number ? old : undefined
  // Only a word that settles the state or the review confirms the record; a comment, edit or auto-merge does not.
  const confirms = patch.state !== undefined || patch.review !== undefined || ctx.source === 'gh'
  const { stale, review: _old, ...rest } = keep ?? {}
  const review = patch.review === null ? undefined : (patch.review ?? keep?.review)

  return {
    ...rest,
    ...(stale && !confirms ? { stale } : {}),
    number: patch.number,
    state: patch.state ?? keep?.state ?? 'open',
    lastAction: patch.lastAction,
    source: ctx.source ?? 'event',
    at,
    sessionId: ctx.sessionId,
    worktree: ctx.worktree,
    ...(patch.url ?? keep?.url ? { url: patch.url ?? keep?.url } : {}),
    ...(review ? { review } : {}),
  }
}

/** A push can change the PR's review state behind our back: keep the record, mark it unconfirmed. */
export const markStale = (rec: PrRecord): PrRecord => (rec.stale ? rec : { ...rec, stale: true })

/** The PR to draw from a record: open ones only; dimmed when a push has gone unconfirmed or it is a day old. */
export function toPr(rec: PrRecord | undefined, now: number): Pr | null {
  if (!rec || rec.state !== 'open') return null
  const dim = rec.stale === true || now - rec.at > DIM_AFTER_MS

  return { number: rec.number, url: rec.url ?? '', ...(rec.review ? { reviewState: rec.review } : {}), ...(dim ? { stale: true } : {}) }
}

/** Does the command pass --draft to `gh pr create`? */
export const hasDraftFlag = (command: string): boolean => /(?:^|\s)(?:--draft|-d)(?:\s|=|$)/.test(command)
