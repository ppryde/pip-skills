import { expect, test } from 'claude-code/testing'
import { claudePidsInTasklist, killArgv, onWindowsPath } from '../plugin/core/windows'
import { configDirTag, otherClaudeDirs, resolveConfigDirs, tildePath } from '../plugin/hooks/register'

test('tasklist rows give the Claude pids', () => {
  const csv = '"claude.exe","1234","Console","1","50,000 K"\r\n"node.exe","77","Console","1","9 K"\r\n"chrome.exe","88","Console","1","9 K"\r\n"System","4","Services","0","1 K"\r\n'
  expect([...claudePidsInTasklist(csv)].sort()).toEqual([1234, 77])
  expect(claudePidsInTasklist('INFO: No tasks are running which match the specified criteria.')).toEqual(new Set())
})

test('killing: kill on POSIX, taskkill /F on Windows', () => {
  expect(killArgv(5, false)).toEqual(['kill', '5'])
  expect(killArgv(5, true)).toEqual(['taskkill', '/PID', '5', '/F'])
})

test('a path says which platform it is on', () => {
  expect(onWindowsPath('C:\\Users\\x\\.claude')).toBe(true)
  expect(onWindowsPath('\\\\srv\\share')).toBe(true)
  expect(onWindowsPath('/home/u/.claude')).toBe(false)
})

test('ROSTER_CONFIG_DIRS: ~ and ~\\ expand with the Windows home, and C:\\U equals c:\\u', () => {
  const dirs = resolveConfigDirs('~\\.claude-work;c:\\users\\x\\.claude;C:\\USERS\\X\\.CLAUDE-WORK', 'C:\\Users\\x', 'C:\\Users\\x\\.claude')
  expect(dirs).toEqual([{ dir: 'C:\\Users\\x\\.claude' }, { dir: 'C:\\Users\\x\\.claude-work', tag: 'work' }])
})

test('other .claude dirs under a Windows home are joined with its separator', () => {
  expect(otherClaudeDirs('C:\\Users\\x', ['.claude', '.claude-work', 'Documents'], ['C:\\Users\\x\\.claude'])).toEqual(['C:\\Users\\x\\.claude-work'])
  expect(configDirTag('C:\\Users\\x\\.claude-work')).toBe('work')
})

test('~ display works for either separator', () => {
  expect(tildePath('C:\\Users\\x\\.claude-work', 'C:\\Users\\x')).toBe('~\\.claude-work')
  expect(tildePath('/home/u/.claude-work', '/home/u')).toBe('~/.claude-work')
  expect(tildePath('/elsewhere', '/home/u')).toBe('/elsewhere')
})

import { mock } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { On } from 'claude-code'

const WIN_CFG = 'C:\\Users\\x\\.claude'
// The kit resolves a relative path against the plugin folder, and `C:\x` is relative here: undo that.
const unresolved = (p: string): string => p.match(/\/([A-Za-z]:\\.*)$/)?.[1] ?? p

function windowsMachine(on: On, env: Record<string, string>) {
  const w = { ran: [] as string[][], sessionsRead: [] as string[] }
  mock.clock(on, { now: 1_000_000 })
  mock.env(on, env)
  on('session.id', () => ({ value: 'self' }))
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('session.surfaces', () => ({ value: ['terminal'] as never }))
  on('store.get', () => ({ value: undefined as never }))
  on('store.set', () => ({ value: undefined }))
  on('fs.list', (_$, e) => {
    const path = unresolved(e.path)
    w.sessionsRead.push(path)
    return path === `${WIN_CFG}\\sessions` ? { value: [{ name: '4321.json', kind: 'file' as const, size: 1, mtimeMs: 0, isLink: false }] } : { deny: 'ENOENT' }
  })
  on('fs.read', (_$, e) => {
    const path = unresolved(e.path)
    return path === `${WIN_CFG}\\sessions\\4321.json`
      ? { value: JSON.stringify({ pid: 4321, sessionId: 'sw', cwd: 'C:\\repo', status: 'busy', updatedAt: 0, startedAt: 0 }) }
      : { deny: 'ENOENT' }
  })
  on('fs.exists', () => ({ value: false }))
  on('ui.open', () => ({ value: { isPlaced: true as const } }))
  on('ui.status', () => ({ value: undefined }))
  on('ui.invalidate', () => ({ value: undefined }))
  on('process.run', (_$, e) => {
    w.ran.push([...e.argv])
    if (['ps', 'tmux', 'id', 'kill'].includes(e.argv[0]!)) throw new Error(`spawn ${e.argv[0]} ENOENT`)
    const stdout = e.argv[0] === 'tasklist' ? '"claude.exe","4321","Console","1","9 K"\r\n' : ''
    return { value: { exitCode: e.argv[0] === 'git' ? 1 : 0, stdout, stderr: '' } as never }
  })

  return w
}

const bridge = ($: Engine) =>
  ($.command.run({ command: 'roster', args: '', origin: { kind: 'bridge' } as never, presentation: { isFullscreen: false, columns: 80 } }) as Promise<{ text: string }>).then(r => r.text)

test('Windows (USERPROFILE only): the registry is read, liveness comes from tasklist, and ps, tmux and id are never run', async ($, on) => {
  const w = windowsMachine(on, { USERPROFILE: 'C:\\Users\\x' })
  const text = await bridge($)

  expect(text).toContain('4321')
  expect(w.sessionsRead).toContain(`${WIN_CFG}\\sessions`)
  expect(w.ran.some(a => a[0] === 'tasklist')).toBe(true)
  expect(w.ran.filter(a => ['ps', 'tmux', 'id'].includes(a[0]!))).toEqual([])
})

test('Windows (HOMEDRIVE+HOMEPATH only) finds the same registry', async ($, on) => {
  const w = windowsMachine(on, { HOMEDRIVE: 'C:', HOMEPATH: '\\Users\\x' })
  expect(await bridge($)).toContain('4321')
  expect(w.sessionsRead).toContain(`${WIN_CFG}\\sessions`)
})

test('no home at all: the roster stays empty and nothing is run, never a "undefined/.claude" read', async ($, on) => {
  const w = windowsMachine(on, {})
  expect(await bridge($)).toContain('0 need you')
  expect(w.sessionsRead.filter(p => p.includes('undefined'))).toEqual([])
  expect(w.ran).toEqual([])
})
