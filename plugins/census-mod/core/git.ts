import type { GitState } from './types'

// Exactly one status call (no untracked scan: the changes segment never counted untracked files).
export const GIT_STATUS_ARGV = ['git', '--no-optional-locks', 'status', '--porcelain=2', '--branch', '-uno'] as const
// Line 1: the git dir (HEAD and index live there, elsewhere for a linked worktree); line 2: the top level.
export const GIT_DIR_ARGV = ['git', 'rev-parse', '--absolute-git-dir', '--show-toplevel'] as const
export const COALESCE_MS = 1000

export type RunOut = { exitCode: number; stdout: string }

/**
 * Port of census's gitcache.parse_status. Detached HEAD reports the short oid; an unborn branch
 * (oid `(initial)`) has no branch to report; untracked (`?`) and ignored (`!`) never count.
 */
export function parseStatus(stdout: string): GitState {
  let head: string | null = null
  let oid: string | null = null
  let upstream: string | null = null
  let ahead = 0
  let uncommitted = 0
  for (const line of stdout.split('\n')) {
    if (line.startsWith('# branch.head ')) head = line.slice('# branch.head '.length).trim()
    else if (line.startsWith('# branch.oid ')) oid = line.slice('# branch.oid '.length).trim()
    else if (line.startsWith('# branch.upstream ')) upstream = line.slice('# branch.upstream '.length).trim()
    else if (line.startsWith('# branch.ab ')) {
      for (const part of line.split(/\s+/).slice(2)) if (/^\+\d+$/.test(part)) ahead = Number.parseInt(part.slice(1), 10)
    } else if (['1 ', '2 ', 'u '].includes(line.slice(0, 2))) uncommitted++
  }
  const detached = head === '(detached)'
  const unborn = oid === '(initial)'
  const branch = detached ? (oid && !unborn ? oid.slice(0, 7) : null) : unborn ? null : head || null
  return { branch, detached, uncommitted, ahead: upstream ? ahead : 0, hasUpstream: upstream !== null }
}

/** What to watch for a `rev-parse --absolute-git-dir --show-toplevel` answer; nothing when it failed. */
export function watchPaths(out: RunOut): string[] {
  const dir = out.exitCode === 0 ? (out.stdout.split('\n')[0] ?? '').trim() : ''
  return dir.startsWith('/') ? [`${dir}/HEAD`, `${dir}/index`] : []
}

/** The linked worktree's top level, or null in the main checkout (git dir is `<repo>/.git`). */
export function worktreeOf(out: RunOut): string | null {
  if (out.exitCode !== 0) return null
  const [dir = '', top = ''] = out.stdout.split('\n').map(l => l.trim())
  return /\/\.git\/worktrees\/[^/]+$/.test(dir) && top.startsWith('/') ? top : null
}

const TOUCH = new Set(['Edit', 'Write', 'NotebookEdit', 'Bash'])
export const touchesGit = (tool: string): boolean => TOUCH.has(tool)
