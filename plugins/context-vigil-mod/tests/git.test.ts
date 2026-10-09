import { expect, test } from 'claude-code/testing'
import { GIT_ARGV, GIT_DIR_ARGV, parseGit, touchesGit, watchPaths } from '../plugin/core/git'

const ok = (stdout: string) => ({ exitCode: 0, stdout })
const fail = { exitCode: 128, stdout: '' }

test('argv: two git questions, branch and status', () => {
  expect(Object.keys(GIT_ARGV)).toEqual(['branch', 'status'])
  expect(GIT_ARGV.branch).toEqual(['git', 'symbolic-ref', '--short', 'HEAD'])
  expect(GIT_ARGV.status).toEqual(['git', 'status', '--porcelain'])
})
test('parse: branch and tracked changes only', () => {
  expect(parseGit(ok('main\n'), ok(' M a.ts\nA  b.ts\n?? new.ts\n'))).toEqual({ branch: 'main', dirty: ['a.ts', 'b.ts'] })
})
test('parse: failures are unknowns, not crashes', () => {
  expect(parseGit(fail, fail)).toEqual({ branch: null, dirty: [] })
  expect(parseGit(ok('main'), ok(''))).toEqual({ branch: 'main', dirty: [] })
})
test('tools that can change git', () => {
  for (const t of ['Edit', 'Write', 'NotebookEdit', 'Bash']) expect(touchesGit(t)).toBe(true)
  for (const t of ['Read', 'Grep', 'Glob', 'mcp__x__y']) expect(touchesGit(t)).toBe(false)
})
test('watch paths come from the real git dir, so a worktree watches its own HEAD and index', () => {
  expect(watchPaths(ok('/repo/.git\n'))).toEqual(['/repo/.git/HEAD', '/repo/.git/index'])
  expect(watchPaths(ok('/repo/.git/worktrees/w2\n'))).toEqual(['/repo/.git/worktrees/w2/HEAD', '/repo/.git/worktrees/w2/index'])
})
test('watch paths: a failed or odd answer watches nothing', () => {
  expect(watchPaths(fail)).toEqual([])
  expect(watchPaths(ok(''))).toEqual([])
  expect(watchPaths(ok('.git'))).toEqual([])
  expect(GIT_DIR_ARGV).toEqual(['git', 'rev-parse', '--absolute-git-dir'])
})
