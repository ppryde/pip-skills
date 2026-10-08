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

export function watchPaths(root: string): string[] {
  return [`${root}/.git/HEAD`, `${root}/.git/index`]
}
