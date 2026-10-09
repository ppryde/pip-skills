import type { Git } from '../types'

// Two questions only: `ahead` was dropped while the status-line band is parked (pre-flight F30).
export const GIT_ARGV = {
  branch: ['git', 'symbolic-ref', '--short', 'HEAD'],
  status: ['git', 'status', '--porcelain'],
} as const

export const COALESCE_MS = 1500

export type RunOut = { exitCode: number; stdout: string }

export function parseGit(branch: RunOut, status: RunOut): Git {
  const b = branch.exitCode === 0 ? branch.stdout.trim() || null : null
  const dirty = status.exitCode === 0
    ? status.stdout.split('\n').filter(l => l.length > 3 && !l.startsWith('??')).map(l => l.slice(3))
    : []
  return { branch: b, dirty }
}

const TOUCH = new Set(['Edit', 'Write', 'NotebookEdit', 'Bash'])
export function touchesGit(tool: string): boolean {
  return TOUCH.has(tool)
}

// The session's own git dir: in a worktree `<root>/.git` is a file, so HEAD and index live elsewhere.
export const GIT_DIR_ARGV = ['git', 'rev-parse', '--absolute-git-dir'] as const

/** What to watch for a `git rev-parse --absolute-git-dir` answer; nothing when it failed. */
export function watchPaths(gitDir: RunOut): string[] {
  const dir = gitDir.exitCode === 0 ? gitDir.stdout.trim() : ''
  return dir.startsWith('/') ? [`${dir}/HEAD`, `${dir}/index`] : []
}
