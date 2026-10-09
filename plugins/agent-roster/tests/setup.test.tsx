import { expect, mock, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { On } from 'claude-code'
import { accountLabel, joinDirs, setupQuestion, splitAnswer, tildePath } from '../plugin/hooks/register'

const PICK = 'Show sessions from these other Claude accounts in the roster too? Pick any, or type other config dirs under Other (comma-separated paths).'
const HOME = '/home'

type Asked = { header: string; question: string; options: string[]; multiSelect: boolean }
type Reg = Record<string, number[]>   // dir -> live pids in its sessions/ folder

/** A fake machine: HOME with `.claude*` dirs holding session registries, `ps` knowing which pids run Claude. */
function machine(on: On, opts: { dirs: Reg; env?: Record<string, string>; answer?: (q: Asked) => string | null; files?: string[]; dead?: number[]; stray?: number; surfaces?: string[] }) {
  const w = {
    asks: [] as Asked[], toasts: [] as string[], logs: [] as string[], store: new Map<string, unknown>(), opened: 0,
    surfaces: { value: opts.surfaces ?? ['terminal'] },
    answer: opts.answer ?? ((q: Asked) => q.options[0] ?? null),
    files: new Set(opts.files ?? []),
  }
  const clock = mock.clock(on, { now: 1_000_000 })
  const registry = (dir: string) => Object.fromEntries((opts.dirs[dir] ?? []).map(pid => [`${pid}.json`, { pid, sessionId: `s${pid}`, cwd: `/r/${pid}`, tmux: `t${pid}:@0.%0`, status: 'busy', updatedAt: 0, startedAt: pid === opts.stray ? Date.now() - 3_600_000 : 0 }]))
  const folders = new Set(Object.keys(opts.dirs).flatMap(d => [d, `${d}/sessions`]))
  on('env.get', ($, e) => ({ value: e.name === 'HOME' ? HOME : e.name === 'CLAUDE_CONFIG_DIR' ? `${HOME}/.claude` : opts.env?.[e.name] }))
  on('session.id', () => ({ value: 'self' }))
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('session.surfaces', () => ({ value: w.surfaces.value as never }))
  on('store.get', (_$, e) => ({ value: w.store.get(e.key) as never }))
  on('store.set', (_$, e) => { w.store.set(e.key, e.value); return { value: undefined } })
  on('fs.list', ($, e) => {
    if (e.path === HOME) return { value: Object.keys(opts.dirs).map(d => ({ name: d.slice(HOME.length + 1), kind: 'dir' as const, size: 0, mtimeMs: 0, isLink: false })).concat([{ name: 'docs', kind: 'dir' as const, size: 0, mtimeMs: 0, isLink: false }]) }
    const dir = e.path.replace(/\/sessions$/, '')
    return opts.dirs[dir] ? { value: Object.keys(registry(dir)).map(name => ({ name, kind: 'file' as const, size: 1, mtimeMs: 0, isLink: false })) } : { deny: 'ENOENT' }
  })
  on('fs.read', ($, e) => {
    const at = e.path.lastIndexOf('/')
    return { value: JSON.stringify((registry(e.path.slice(0, at).replace(/\/sessions$/, '')) as Record<string, object>)[e.path.slice(at + 1)]) }
  })
  on('fs.exists', (_$, e) => ({ value: folders.has(e.path) || w.files.has(e.path) }))
  on('ui.open', () => { w.opened++; return { value: { isPlaced: true as const } } })
  on('ui.status', () => ({ value: undefined }))
  on('ui.invalidate', () => ({ value: undefined }))
  on('ui.toast', (_$, e) => { w.toasts.push(e.text); return { value: undefined } })
  on('ui.log', (_$, e) => { w.logs.push(e.text); return { value: undefined } })
  on('process.run', (_$, e) => {
    const pids = new Set(Object.values(opts.dirs).flat().filter(p => !(opts.dead ?? []).includes(p)))
    let stdout = ''
    if (e.argv[0] === 'ps' && e.argv.includes('-ax')) stdout = opts.stray ? `${opts.stray} 1 01:00:00 /v/2.1.289\n` : ''
    else if (e.argv[0] === 'ps') stdout = [...pids].map(p => `${p} /bin/claude`).join('\n') + '\n'
    else if (e.argv[0] === 'id') stdout = '501\n'
    else if (e.argv[0] === 'tmux' && e.argv.includes('list-panes') && e.argv.includes('-a') && opts.stray) stdout = `cc-stray\t${opts.stray}\t2.1.289\t/r/s\t${Math.floor(Date.now() / 1000) - 30}\n`
    return { value: { exitCode: e.argv[0] === 'git' ? 1 : 0, stdout, stderr: '' } as never }
  })
  on('tool.call', (_$, e) => {
    const input = e as unknown as { tool: string; questions?: { question: string; header?: string; multiSelect?: boolean; options?: (string | { label: string })[] }[] }
    if (input.tool !== 'AskUserQuestion') return { result: 'ok' } as never
    const answers: Record<string, string> = {}
    for (const q of input.questions ?? []) {
      const seen = { header: q.header ?? '', question: q.question, options: (q.options ?? []).map(o => (typeof o === 'string' ? o : o.label)), multiSelect: Boolean(q.multiSelect) }
      w.asks.push(seen)
      const a = w.answer(seen)
      if (a === null) return { deny: 'dismissed' } as never
      answers[q.question] = a
    }
    return { result: { questions: input.questions, answers } } as never
  })
  return { w, clock }
}

const roster = ($: Engine, args: string) =>
  $.command.run({ command: 'roster', args, origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 80 } }) as Promise<{ text: string }>

const DIRS: Reg = { '/home/.claude': [1], '/home/.claude-work': [21, 22, 23], '/home/.claude-personal': [31], '/home/.claude-empty': [] }

test('the question texts, exactly', async () => {
  const q = setupQuestion([{ dir: '/home/.claude-work', tag: 'work', live: 3 }], [], HOME)
  expect(q).toEqual({ header: '👥 Accounts', question: PICK, options: ['work — 3 live (~/.claude-work)'], multiSelect: true })
  expect(setupQuestion([], [], HOME)).toEqual({
    header: '👥 Accounts', question: 'No other accounts found. Add a config dir?', options: ['No, just this account', 'Type a config dir under Other'],
  })
})

test('pure helpers: labels, tilde paths, separators, answers', async () => {
  expect(tildePath('/home/.claude-work', HOME)).toBe('~/.claude-work')
  expect(tildePath('/srv/claude', HOME)).toBe('/srv/claude')
  expect(accountLabel({ dir: '/home/.claude-work', tag: 'work', live: 0 }, HOME)).toBe('work — 0 live (~/.claude-work)')
  expect(joinDirs(['/a', '/b'])).toBe('/a:/b')
  expect(joinDirs(['C:\\a', 'D:\\b'])).toBe('C:\\a;D:\\b')
  expect(splitAnswer('a, b ,~/x', ['a', 'b'])).toEqual({ chosen: ['a', 'b'], typed: ['~/x'] })
  expect(splitAnswer('No, just this account', ['No, just this account', 'x'])).toEqual({ chosen: ['No, just this account'], typed: [] })
})

test('discovery lists the other dirs with live counts, the busiest first, and leaves out the own dir and empty homes', async ($, on) => {
  const { w, clock } = machine(on, { dirs: DIRS })
  await roster($, 'setup')
  await clock.settle()
  const q = w.asks[0]!

  expect(q.question).toBe(PICK)
  expect(q.multiSelect).toBe(true)
  expect(q.options).toEqual(['work — 3 live (~/.claude-work)', 'personal — 1 live (~/.claude-personal)', 'empty — 0 live (~/.claude-empty)'])
  expect(q.options.join()).not.toContain('(~/.claude)')
})

test('more than four dirs: the top four are options and the question names the rest', async ($, on) => {
  const dirs: Reg = { '/home/.claude': [1] }
  for (const [i, n] of [5, 4, 3, 2, 1, 1].entries()) dirs[`/home/.claude-a${i}`] = Array.from({ length: n }, (_, k) => 100 * (i + 1) + k)
  const { w, clock } = machine(on, { dirs })
  await roster($, 'setup')
  await clock.settle()
  const q = w.asks[0]!

  expect(q.options).toHaveLength(4)
  expect(q.options[0]).toContain('a0 — 5 live')
  expect(q.question).toContain('2 more found (a4, a5): type their paths under Other.')
})

test('none found: the two-option question, and No saves nothing to show', async ($, on) => {
  const { w, clock } = machine(on, { dirs: { '/home/.claude': [1] }, answer: q => q.options[0]! })
  await roster($, 'setup')
  await clock.settle()

  expect(w.asks[0]).toMatchObject({ question: 'No other accounts found. Add a config dir?', options: ['No, just this account', 'Type a config dir under Other'], multiSelect: false })
  expect(w.store.get('roster:configDirs')).toEqual([])
  expect(w.toasts.at(-1)).toBe('👥 Roster now shows: this account only.')
})

test('a multi-select answer saves the chosen dirs and the confirmation counts their live sessions', async ($, on) => {
  const { w, clock } = machine(on, { dirs: DIRS, answer: q => q.options.slice(0, 2).join(',') })
  await roster($, 'setup')
  await clock.settle()

  expect(w.store.get('roster:configDirs')).toEqual(['/home/.claude-work', '/home/.claude-personal'])
  expect(w.toasts.at(-1)).toBe('👥 Roster now shows: this account + work, personal (4 live sessions).')
  expect(w.logs.at(-1)).toBe(w.toasts.at(-1))
})

test('Other text: valid paths are kept, missing dirs and dirs without sessions/ are reported by name', async ($, on) => {
  const { w, clock } = machine(on, {
    dirs: { ...DIRS, '/srv/claude-x': [41] },
    files: ['/srv/nosessions', '/home/.claude-work/sessions'],
    answer: q => [q.options[0], '~/.claude-personal', '/srv/claude-x', '/srv/gone', '/srv/nosessions', 'relative/dir'].join(', '),
  })
  await roster($, 'setup')
  await clock.settle()

  expect(w.store.get('roster:configDirs')).toEqual(['/home/.claude-work', '/home/.claude-personal', '/srv/claude-x'])
  const said = w.toasts.at(-1)!
  expect(said).toContain('Not added: /srv/gone (no such folder); /srv/nosessions (no sessions/ folder); relative/dir (not an absolute path).')
  expect(said).toContain('this account + work, personal, claude-x')
})

test('the own dir typed under Other is not added twice', async ($, on) => {
  const { w, clock } = machine(on, { dirs: DIRS, answer: () => '~/.claude' })
  await roster($, 'setup')
  await clock.settle()

  expect(w.store.get('roster:configDirs')).toEqual([])
})

test('dismissing changes nothing and says so', async ($, on) => {
  const { w, clock } = machine(on, { dirs: DIRS, answer: () => null })
  w.store.set('roster:configDirs', ['/home/.claude-work'])
  await roster($, 'setup')
  await clock.settle()

  expect(w.store.get('roster:configDirs')).toEqual(['/home/.claude-work'])
  expect(w.toasts.at(-1)).toMatch(/dismissed — nothing changed/)
})

test('re-running lists the current choices in the question', async ($, on) => {
  const { w, clock } = machine(on, { dirs: DIRS })
  w.store.set('roster:configDirs', ['/home/.claude-work', '/home/.claude-personal'])
  await roster($, 'setup')
  await clock.settle()

  expect(w.asks[0]!.question).toContain('Showing now: work, personal.')
})

const bridge = ($: Engine) =>
  ($.command.run({ command: 'roster', args: '', origin: { kind: 'bridge' } as never, presentation: { isFullscreen: false, columns: 80 } }) as Promise<{ text: string }>).then(r => r.text)

test('the saved list is what the roster reads', async ($, on) => {
  const { w } = machine(on, { dirs: DIRS })
  w.store.set('roster:configDirs', ['/home/.claude-work'])
  const text = await bridge($)

  expect(text).toContain('t21')       // the saved dir's sessions are listed
  expect(text).not.toContain('t31')   // an unsaved one is not
})

test('ROSTER_CONFIG_DIRS outranks the saved list, and setup says so', async ($, on) => {
  const { w, clock } = machine(on, { dirs: DIRS, env: { ROSTER_CONFIG_DIRS: '~/.claude-personal' }, answer: q => q.options[0]! })
  w.store.set('roster:configDirs', ['/home/.claude-work'])
  const text = await bridge($)

  expect(text).toContain('t31')
  expect(text).not.toContain('t21')
  await roster($, 'setup')
  await clock.settle()
  expect(w.toasts.at(-1)).toContain('ROSTER_CONFIG_DIRS is set and overrides this list')
})

test('a second /roster setup while one is pending opens no second question', async ($, on) => {
  const { w, clock } = machine(on, { dirs: DIRS })
  await roster($, 'setup')
  await roster($, 'setup')
  await clock.settle()

  expect(w.asks).toHaveLength(1)
})

// ---- the one-time offer -----------------------------------------------------------------------------

const STRAY_DIRS: Reg = { '/home/.claude': [1], '/home/.claude-work': [777] }

test('the first time a pane of another account turns up, setup is offered once', async ($, on) => {
  const { w, clock } = machine(on, { dirs: STRAY_DIRS, stray: 777, answer: () => null })
  await bridge($)   // a scan sees the stray pane
  await clock.settle()

  expect(w.asks).toHaveLength(1)
  expect(w.store.get('roster:setupOffered')).toBe(true)
  await bridge($)
  await clock.settle()
  expect(w.asks).toHaveLength(1)   // a dismissal is an answer: not offered again
})

test('the offer is not made when ROSTER_CONFIG_DIRS is set, or after the flag', async ($, on) => {
  const withEnv = machine(on, { dirs: STRAY_DIRS, stray: 777, env: { ROSTER_CONFIG_DIRS: '~/.claude-personal' } })
  await bridge($)
  await withEnv.clock.settle()
  expect(withEnv.w.asks).toHaveLength(0)
})

test('an answered offer is not repeated, and its note points at /roster setup', async ($, on) => {
  const { w, clock } = machine(on, { dirs: STRAY_DIRS, stray: 777, answer: () => '~/nowhere' })
  const text = await bridge($)
  await clock.settle()

  expect(text).toContain('running in another account (work) — run /roster setup to list it')
  expect(text).not.toContain('set ROSTER_CONFIG_DIRS to list it')
  expect(w.asks).toHaveLength(1)
  await bridge($)
  await clock.settle()
  expect(w.asks).toHaveLength(1)
})

const START = (isInteractive: boolean, surface: 'terminal' | 'desktop' = 'terminal') => ({ cwd: '/r', surface, isInteractive }) as never

test('a headless run (-p, SDK) neither asks nor spends the one-time offer', async ($, on) => {
  const { w, clock } = machine(on, { dirs: STRAY_DIRS, stray: 777 })
  await $.session.start(START(false))
  await bridge($)
  await clock.settle()

  expect(w.asks).toHaveLength(0)
  expect(w.store.get('roster:setupOffered')).toBeUndefined()
})

test('no terminal or desktop attached: no offer, flag untouched, and a later session that can ask still gets it', async ($, on) => {
  const { w, clock } = machine(on, { dirs: STRAY_DIRS, stray: 777, surfaces: [] })
  await $.session.start(START(true))
  await bridge($)
  await clock.settle()
  expect(w.asks).toHaveLength(0)
  expect(w.store.get('roster:setupOffered')).toBeUndefined()

  w.surfaces.value = ['terminal']
  await bridge($)
  await clock.settle()
  expect(w.asks).toHaveLength(1)
  expect(w.store.get('roster:setupOffered')).toBe(true)
})

test('an interactive desktop session is offered it too', async ($, on) => {
  const { w, clock } = machine(on, { dirs: STRAY_DIRS, stray: 777, surfaces: ['desktop'], answer: q => q.options[0]! })
  await $.session.start(START(true, 'desktop'))
  await bridge($)
  await clock.settle()

  expect(w.asks).toHaveLength(1)
})

test('a dismissal by someone who could answer spends the offer', async ($, on) => {
  const { w, clock } = machine(on, { dirs: STRAY_DIRS, stray: 777, answer: () => null })
  await $.session.start(START(true))
  await roster($, 'setup')
  await clock.settle()

  expect(w.store.get('roster:setupOffered')).toBe(true)
})

test('a rejection with nobody left to ask does not spend the offer', async ($, on) => {
  const { w, clock } = machine(on, { dirs: STRAY_DIRS, stray: 777, answer: () => null, surfaces: [] })
  await $.session.start(START(true))
  await roster($, 'setup')
  await clock.settle()

  expect(w.asks).toHaveLength(1)
  expect(w.store.get('roster:setupOffered')).toBeUndefined()
})

test('no stray pane, no offer', async ($, on) => {
  const { w, clock } = machine(on, { dirs: DIRS })
  await bridge($)
  await clock.settle()

  expect(w.asks).toHaveLength(0)
})
