import { expect, test } from 'claude-code/testing'
import { isClaudeCommand, killArgv, onWindowsPath, procListArgv, procsInList } from '../plugin/core/windows'
import { configDirTag, otherClaudeDirs, resolveConfigDirs, tildePath } from '../plugin/hooks/register'

test('the process list script names only integer pids, and a non-pid never reaches it', () => {
  expect(procListArgv([1234, 99])?.at(-1)).toContain("-Filter 'ProcessId=1234 OR ProcessId=99'")
  expect(procListArgv([4321, Number.NaN, 1.5, 3])?.at(-1)).toContain("-Filter 'ProcessId=4321'")
  expect(procListArgv([])).toBeNull()
  expect(procListArgv([0, 4])).toBeNull()
})

test('the process list parses to creation time and command line', () => {
  const out = '1234\t1791000000000\t"C:\\Users\\x\\.local\\bin\\claude.exe" --resume\r\n77\t5\tnode.exe app.js\r\nnoise\r\n'
  const procs = procsInList(out)
  expect(procs.get(1234)).toEqual({ createdMs: 1791000000000, command: '"C:\\Users\\x\\.local\\bin\\claude.exe" --resume' })
  expect(procs.get(77)?.command).toBe('node.exe app.js')
  expect(procs.size).toBe(2)
})

test('Claude means its own executable or claude-code\'s entrypoint, never a bare node or bun', () => {
  expect(isClaudeCommand('"C:\\Users\\x\\.local\\bin\\claude.exe" --resume')).toBe(true)
  expect(isClaudeCommand('claude')).toBe(true)
  expect(isClaudeCommand('node C:\\Users\\x\\AppData\\npm\\node_modules\\@anthropic-ai\\claude-code\\cli.js')).toBe(true)
  expect(isClaudeCommand('node.exe server.js')).toBe(false)
  expect(isClaudeCommand('"C:\\Program Files\\nodejs\\node.exe" C:\\app\\claude-notes\\index.js')).toBe(false)
  expect(isClaudeCommand('bun.exe run dev')).toBe(false)
  expect(isClaudeCommand('')).toBe(false)
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
  const w = { ran: [] as string[][], sessionsRead: [] as string[], STARTED: Date.now() - 30_000, psOut: { value: '' }, psFails: { value: false }, killed: [] as string[][] }
  w.psOut.value = `4321\t${w.STARTED}\t"C:\\bin\\claude.exe" --x\r\n`
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
      ? { value: JSON.stringify({ pid: 4321, sessionId: 'sw', cwd: 'C:\\repo', status: 'busy', updatedAt: 0, startedAt: w.STARTED }) }
      : { deny: 'ENOENT' }
  })
  on('fs.exists', () => ({ value: false }))
  on('ui.open', () => ({ value: { isPlaced: true as const } }))
  on('ui.status', () => ({ value: undefined }))
  on('ui.invalidate', () => ({ value: undefined }))
  on('process.run', (_$, e) => {
    w.ran.push([...e.argv])
    if (['ps', 'tmux', 'id', 'kill'].includes(e.argv[0]!)) throw new Error(`spawn ${e.argv[0]} ENOENT`)
    const stdout = e.argv[0] === 'powershell' ? w.psOut.value : ''
    if (e.argv[0] === 'taskkill') w.killed.push([...e.argv])
    return { value: { exitCode: e.argv[0] === 'git' || (e.argv[0] === 'powershell' && w.psFails.value) ? 1 : 0, stdout, stderr: '' } as never }
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
  expect(w.ran.some(a => a[0] === 'powershell')).toBe(true)
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

const kill = ($: Engine) =>
  ($.command.run({ command: 'roster', args: 'kill 4321', origin: { kind: 'bridge' } as never, presentation: { isFullscreen: false, columns: 80 } }) as Promise<{ text: string }>).then(r => r.text)

test('Windows kill: command line and start time both match, so taskkill runs', async ($, on) => {
  const w = windowsMachine(on, { USERPROFILE: 'C:\\Users\\x' })
  await bridge($)
  expect(await kill($)).toContain('Ended')
  expect(w.killed).toEqual([['taskkill', '/PID', '4321', '/F']])
})

test('Windows kill refuses a reused pid: a bare node.exe is not Claude', async ($, on) => {
  const w = windowsMachine(on, { USERPROFILE: 'C:\\Users\\x' })
  w.psOut.value = `4321\t${w.STARTED}\tnode.exe server.js\r\n`
  expect(await bridge($)).not.toContain('4321') // not even listed
  expect(await kill($)).toContain('No live session')
  expect(w.killed).toEqual([])
})

test('Windows kill refuses when the process was created at another time than the registry says', async ($, on) => {
  const w = windowsMachine(on, { USERPROFILE: 'C:\\Users\\x' })
  w.psOut.value = `4321\t${w.STARTED + 3_600_000}\t"C:\\bin\\claude.exe"\r\n`
  await bridge($)
  expect(await kill($)).toContain('Refused')
  expect(w.killed).toEqual([])
})

test('Windows kill refuses when the OS cannot be asked', async ($, on) => {
  const w = windowsMachine(on, { USERPROFILE: 'C:\\Users\\x' })
  await bridge($)
  w.psFails.value = true
  expect(await kill($)).toContain('Refused')
  expect(w.killed).toEqual([])
})
