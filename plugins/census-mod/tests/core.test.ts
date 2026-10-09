import { expect, test } from 'claude-code/testing'
import { EMPTY_COUNTERS, TAIL_CMD, addTurn, compacted, expiresAtMs, isWarm, parseWrites, ratio, sessionRatio, ttlFromWrites, withTtl } from '../plugin/core/cache'
import { COALESCE_MS, ancestors, compareVersions, delayFor, endTimeoutMs, findSibling, highestVersion, ingestArgv, ingestEnv, pointerFiles } from '../plugin/core/census'
import { GIT_DIR_ARGV, GIT_STATUS_ARGV, parseStatus, touchesGit, watchPaths, worktreeOf } from '../plugin/core/git'
import { BACKOFF_MS, ghArgv, parsePrList, shouldRefresh, touchesPr } from '../plugin/core/gh'
import { findProc, lastTitle } from '../plugin/core/registry'

const T0 = 1_791_000_000_000
const USAGE = { input_tokens: 2, output_tokens: 100, cache_read_input_tokens: 90, cache_creation_input_tokens: 8 }

// ---- cache ----------------------------------------------------------------------------------

test('a turn adds its summed usage; requests counts turns; the ratio is read / (read + write + uncached)', async () => {
  const c = addTurn(addTurn(EMPTY_COUNTERS, USAGE, T0), { ...USAGE, cache_read_input_tokens: 0, cache_creation_input_tokens: 100, input_tokens: 0 }, T0 + 1000)

  expect(c).toMatchObject({ requests: 2, input: 2, read: 90, create: 108, output: 200, lastTurnAt: T0 + 1000, cold: false })
  expect(c.lastRatio).toBe(0) // the last turn alone read nothing
  expect(sessionRatio(c)).toBe(90 / 200)
  expect(ratio(0, 0, 0)).toBeNull()
})

test('warm until the last turn plus the ttl; a compaction is cold until the next turn', async () => {
  const c = withTtl(addTurn(EMPTY_COUNTERS, USAGE, T0), '1h')

  expect(expiresAtMs(c, '1h')).toBe(T0 + 3_600_000)
  expect(isWarm(c, '1h', T0 + 3_599_999)).toBe(true)
  expect(isWarm(c, '1h', T0 + 3_600_000)).toBe(false)
  expect(isWarm(c, '5m', T0 + 300_000)).toBe(false)
  expect(isWarm(compacted(c, T0 + 5), '1h', T0 + 10)).toBe(false)
  expect(isWarm(addTurn(compacted(c, T0 + 5), USAGE, T0 + 20), '1h', T0 + 30)).toBe(true)
  expect(isWarm(EMPTY_COUNTERS, '5m', T0)).toBe(false)
})

test('the ttl is read off the transcript tail: any 5m write makes it 5m, none found is unknown', async () => {
  const row = (m5: number, h1: number) => `"cache_creation":{"ephemeral_5m_input_tokens":${m5},"ephemeral_1h_input_tokens":${h1}}\n`

  expect(ttlFromWrites(parseWrites(row(0, 120)))).toBe('1h')
  expect(ttlFromWrites(parseWrites(row(0, 120) + row(10, 0)))).toBe('5m')
  expect(ttlFromWrites(parseWrites(row(0, 0)))).toBeNull()
  expect(ttlFromWrites(parseWrites(''))).toBeNull()
  expect(TAIL_CMD).toContain('tail -c 65536')
})

// ---- census CLI discovery and the ingest call ---------------------------------------------------

test('pointers: the shadow dir first, then the census dir (CENSUS_STORE, else the config dir)', async () => {
  expect(pointerFiles({ CLAUDE_CONFIG_DIR: '/cfg' })).toEqual(['/cfg/census/cli.path'])
  expect(pointerFiles({ CLAUDE_CONFIG_DIR: '/cfg', CENSUS_STORE: '/store/' })).toEqual(['/store/cli.path'])
  expect(pointerFiles({ CLAUDE_CONFIG_DIR: '/cfg', CENSUS_MOD_STORE: '~/shadow' , HOME: '/home/u' })).toEqual(['/home/u/shadow/cli.path', '/cfg/census/cli.path'])
  expect(pointerFiles({ HOME: '/home/u' })).toEqual(['/home/u/.claude/census/cli.path'])
  expect(pointerFiles({})).toEqual([])
})

test('a .py runs under python3, anything else is the executable; shadow mode sets CENSUS_STORE for the child', async () => {
  expect(ingestArgv('/x/cli.py')).toEqual(['python3', '/x/cli.py', 'ingest'])
  expect(ingestArgv('/usr/local/bin/census')).toEqual(['/usr/local/bin/census', 'ingest'])
  expect(ingestEnv({})).toBeUndefined()
  expect(ingestEnv({ CENSUS_MOD_STORE: '/cfg/census-shadow' })).toEqual({ CENSUS_STORE: '/cfg/census-shadow' })
})

test('ingests are 2 s apart; the final one fits what is left of the session.end budget', async () => {
  expect(COALESCE_MS).toBe(2000)
  expect(delayFor(T0, null)).toBe(0)
  expect(delayFor(T0 + 500, T0)).toBe(1500)
  expect(delayFor(T0 + 2500, T0)).toBe(0)
  expect(endTimeoutMs(1500)).toBe(1000)
  expect(endTimeoutMs(900)).toBe(700)
  expect(endTimeoutMs(300)).toBe(100)
  expect(endTimeoutMs(299)).toBeNull() // too little left: skip, never overrun
  expect(endTimeoutMs(0)).toBeNull()
  expect(endTimeoutMs(Number.POSITIVE_INFINITY)).toBe(1000)
})

// ---- git ------------------------------------------------------------------------------------

test('git is asked one question, with no optional locks and no untracked scan', async () => {
  expect([...GIT_STATUS_ARGV]).toEqual(['git', '--no-optional-locks', 'status', '--porcelain=2', '--branch', '-uno'])
  expect([...GIT_DIR_ARGV]).toEqual(['git', 'rev-parse', '--absolute-git-dir', '--show-toplevel'])
})

test('porcelain v2: branch, upstream, ahead, uncommitted (ordinary, renamed, unmerged); detached and unborn follow census', async () => {
  const head = '# branch.oid abc1234def5678\n# branch.head feat/x\n# branch.upstream origin/feat/x\n# branch.ab +3 -1\n'
  expect(parseStatus(`${head}1 .M N... 1 1 1 a b f\n2 R. N... 1 1 1 a b R100 g\th\nu UU N... 1 1 1 1 a b c d\n? new\n! ign\n`)).toEqual({
    branch: 'feat/x', detached: false, uncommitted: 3, ahead: 3, hasUpstream: true,
  })
  expect(parseStatus('# branch.oid abc1234def\n# branch.head main\n# branch.ab +2 -0\n').ahead).toBe(0) // no upstream: nothing to be ahead of
  expect(parseStatus('# branch.oid abc1234def5678\n# branch.head (detached)\n')).toMatchObject({ branch: 'abc1234', detached: true })
  expect(parseStatus('# branch.oid (initial)\n# branch.head main\n')).toMatchObject({ branch: null, detached: false })
  expect(parseStatus('# branch.oid (initial)\n# branch.head (detached)\n').branch).toBeNull()
})

test('HEAD and the index are watched where git keeps them; a linked worktree is told by its git dir', async () => {
  expect(watchPaths({ exitCode: 0, stdout: '/repo/.git/worktrees/w\n/wt\n' })).toEqual(['/repo/.git/worktrees/w/HEAD', '/repo/.git/worktrees/w/index'])
  expect(watchPaths({ exitCode: 128, stdout: '' })).toEqual([])
  expect(worktreeOf({ exitCode: 0, stdout: '/repo/.git/worktrees/w\n/wt\n' })).toBe('/wt')
  expect(worktreeOf({ exitCode: 0, stdout: '/repo/.git\n/repo\n' })).toBeNull()
  expect(worktreeOf({ exitCode: 128, stdout: '' })).toBeNull()
  expect(touchesGit('Edit') && touchesGit('Bash') && !touchesGit('Read')).toBe(true)
})

// ---- gh -------------------------------------------------------------------------------------

test('gh is asked for the open PR of this branch, and nothing else', async () => {
  expect(ghArgv('feat/x')).toEqual(['gh', 'pr', 'list', '--head', 'feat/x', '--state', 'open', '--limit', '1', '--json', 'number,url,reviewDecision'])
})

test('the review decision keeps the spellings census already stores; empty leaves the key out', async () => {
  const one = (d: string) => parsePrList(JSON.stringify([{ number: 7, url: 'u', reviewDecision: d }]))
  expect(one('APPROVED')).toEqual({ number: 7, url: 'u', reviewState: 'approved' })
  expect(one('REVIEW_REQUIRED')).toEqual({ number: 7, url: 'u', reviewState: 'pending' })
  expect(one('CHANGES_REQUESTED')).toEqual({ number: 7, url: 'u', reviewState: 'changes_requested' })
  expect(one('')).toEqual({ number: 7, url: 'u' })
  expect(parsePrList('[]')).toBeNull()
  expect(parsePrList('not json')).toBeUndefined()
  expect(parsePrList('{}')).toBeUndefined()
})

test('gh runs on a branch change, after git push / gh pr, or when stale and the session is active; never inside the backoff', async () => {
  const entry = { at: T0, pr: null }
  expect(shouldRefresh('branch', undefined, T0, null)).toBe(true)
  expect(shouldRefresh('branch', entry, T0 + 1, null)).toBe(true)
  expect(shouldRefresh('push', entry, T0 + 1, null)).toBe(true)
  expect(shouldRefresh('age', entry, T0 + 9 * 60_000, T0 + 9 * 60_000)).toBe(false) // fresh enough
  expect(shouldRefresh('age', entry, T0 + 11 * 60_000, T0 + 10.5 * 60_000)).toBe(true)
  expect(shouldRefresh('age', entry, T0 + 11 * 60_000, T0)).toBe(false) // session idle
  expect(shouldRefresh('age', entry, T0 + 11 * 60_000, null)).toBe(false)
  const failed = { at: T0, pr: null, failedAt: T0 }
  expect(shouldRefresh('push', failed, T0 + BACKOFF_MS - 1, T0)).toBe(false)
  expect(shouldRefresh('push', failed, T0 + BACKOFF_MS, T0)).toBe(true)
  expect(touchesPr('git push origin x') && touchesPr('gh pr create') && !touchesPr('git status')).toBe(true)
})

// ---- registry and name ------------------------------------------------------------------------

test('our process is the registry entry whose sessionId is ours', async () => {
  const file = (o: object) => ({ text: JSON.stringify(o) })
  const files = [file({ pid: 1, sessionId: 'x', procStart: 'a' }), { text: '{broken' }, file({ pid: 22695, sessionId: 's1', procStart: 'Sun Oct  4 22:57:51 2026', version: '2.1.289' })]

  expect(findProc(files, 's1')).toEqual({ pid: 22695, procStart: 'Sun Oct  4 22:57:51 2026', version: '2.1.289' })
  expect(findProc(files, 'nobody')).toBeNull()
  expect(findProc([file({ pid: 1, sessionId: 's1', procStart: 'a' })], 's1')).toBeNull() // pid 1 is never a session
})

test('the session name is the last custom-title row', async () => {
  const rows = '{"type":"custom-title","customTitle":"Old","sessionId":"s"}\n{"type":"custom-title","customTitle":" New name ","sessionId":"s"}\n{"type":"custom-ti'
  expect(lastTitle(rows)).toBe('New name')
  expect(lastTitle('')).toBeNull()
})

// ---- a census plugin installed beside this one ------------------------------------------------

const fsOf = (files: string[], dirs: Record<string, string[]> = {}) => ({
  exists: async (p: string) => files.includes(p),
  list: async (p: string) => {
    const names = dirs[p]
    if (!names) throw new Error('ENOENT')
    return names.map(name => ({ name }))
  },
})

test('ancestors, nearest first, and version order is numeric (0.10.0 over 0.9.0)', async () => {
  expect(ancestors('/a/b/census-mod')).toEqual(['/a/b', '/a', '/'])
  expect(highestVersion(['0.9.0', '0.10.0', '0.2.5'])).toBe('0.10.0')
  expect(highestVersion([])).toBeNull()
  expect(compareVersions('1.0.0', '1.0')).toBe(0)
})

test('a repo checkout: <plugins>/census/scripts/cli.py, found by walking up', async () => {
  const fs = fsOf(['/repo/plugins/census/scripts/cli.py'])

  expect(await findSibling(fs, '/repo/plugins/census-mod')).toBe('/repo/plugins/census/scripts/cli.py')
  expect(await findSibling(fs, '/repo/plugins/census-mod/hooks')).toBe('/repo/plugins/census/scripts/cli.py')
  expect(await findSibling(fs, '/repo/plugins/census-mod/plugin')).toBe('/repo/plugins/census/scripts/cli.py')
  expect(await findSibling(fs, '/elsewhere/census-mod')).toBeNull()
})

test('a marketplace cache: <cache>/<mkt>/census/<version>/scripts/cli.py, the highest version wins', async () => {
  const base = '/cfg/plugins/cache/pip-skills/census'
  const fs = fsOf(
    [`${base}/0.9.0/scripts/cli.py`, `${base}/0.10.0/scripts/cli.py`, `${base}/0.2.0/scripts/cli.py`],
    { [base]: ['0.9.0', '0.10.0', '0.2.0'] },
  )

  expect(await findSibling(fs, '/cfg/plugins/cache/pip-skills/census-mod/0.1.0')).toBe(`${base}/0.10.0/scripts/cli.py`)
})

test('an orphaned version dir is skipped, even when it is the highest', async () => {
  const base = '/cache/pip-skills/census'
  const fs = fsOf(
    [`${base}/0.9.0/scripts/cli.py`, `${base}/0.10.0/scripts/cli.py`, `${base}/0.10.0/.orphaned_at`],
    { [base]: ['0.9.0', '0.10.0'] },
  )

  expect(await findSibling(fs, '/cache/pip-skills/census-mod/0.1.0')).toBe(`${base}/0.9.0/scripts/cli.py`)
})

test('a version dir with no CLI in it, or only orphans, is nothing', async () => {
  const base = '/cache/pip-skills/census'
  const fs = fsOf([`${base}/0.1.0/.orphaned_at`, `${base}/0.1.0/scripts/cli.py`], { [base]: ['0.1.0', '0.2.0'] })

  expect(await findSibling(fs, '/cache/pip-skills/census-mod/0.1.0')).toBeNull()
})
