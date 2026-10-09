import type { Pr } from './types'

export const GH_TIMEOUT_MS = 5000
export const BACKOFF_MS = 10 * 60_000
export const MAX_AGE_MS = 10 * 60_000
export const ACTIVE_MS = 10 * 60_000

/** Exactly: gh pr list --head <branch> --state open --limit 1 --json number,url,reviewDecision */
export const ghArgv = (branch: string): string[] =>
  ['gh', 'pr', 'list', '--head', branch, '--state', 'open', '--limit', '1', '--json', 'number,url,reviewDecision']

/** What is kept per repo+branch. `pr: null` = checked, no open PR. */
export type GhEntry = { at: number; pr: Pr | null; failedAt?: number }

const REVIEW: Record<string, string> = {
  APPROVED: 'approved',
  REVIEW_REQUIRED: 'pending',
  CHANGES_REQUESTED: 'changes_requested',
}

/** `gh pr list` JSON to a PR; empty list = no open PR; undefined = not parseable. */
export function parsePrList(stdout: string): Pr | null | undefined {
  let data: unknown
  try {
    data = JSON.parse(stdout)
  } catch {
    return undefined
  }
  if (!Array.isArray(data)) return undefined
  const first = data[0] as { number?: unknown; url?: unknown; reviewDecision?: unknown } | undefined
  if (first === undefined) return null
  if (typeof first.number !== 'number') return undefined
  const pr: Pr = { number: first.number, url: typeof first.url === 'string' ? first.url : '' }
  const state = typeof first.reviewDecision === 'string' ? REVIEW[first.reviewDecision] : undefined
  if (state) pr.reviewState = state
  return pr
}

/** `start`: the first sight of a branch by a bound session (a start, a /clear, a restart): a fresh cached answer stands. */
export type Why = 'branch' | 'push' | 'age' | 'start'

/** A Bash command that can have opened, updated or closed a PR. */
export const touchesPr = (command: string): boolean => command.includes('git push') || command.includes('gh pr')

export function shouldRefresh(why: Why, entry: GhEntry | undefined, now: number, lastActiveAt: number | null): boolean {
  if (entry?.failedAt !== undefined && now < entry.failedAt + BACKOFF_MS) return false
  if (entry === undefined) return true
  if (why === 'branch' || why === 'push') return true
  if (why === 'start') return now - entry.at > MAX_AGE_MS
  return now - entry.at > MAX_AGE_MS && lastActiveAt !== null && now - lastActiveAt < ACTIVE_MS
}

/** JSON-encoded pair: any root/branch (a `|` in either included) maps to its own key. */
export const ghKey = (root: string, branch: string): string => `gh:${JSON.stringify([root, branch])}`
