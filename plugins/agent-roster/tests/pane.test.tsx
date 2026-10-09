import { expect, mock, test } from 'claude-code/testing'
import type { Engine } from 'claude-code/testing'
import type { On } from 'claude-code'

// The test's hooks stand for the engine beneath the mod: a fake HOME holding
// a session registry, `ps` reporting every pid alive, no git, no
// transcripts.
const REGISTRY: Record<string, object> = {
  '101.json': { pid: 101, sessionId: 'a', cwd: '/r/pip-skills', tmux: 'cc-a-1:@0.%0', status: 'waiting', updatedAt: 0 },
  '102.json': { pid: 102, sessionId: 'b', cwd: '/r/warehouse', tmux: 'cc-b-1:@1.%1', status: 'busy', updatedAt: 0 },
  '103.json': { pid: 103, sessionId: 'c', cwd: '/r/pip-skills', tmux: 'cc-a-2:@2.%2', status: 'idle', updatedAt: 0 },
}
const SESSIONS_DIR = '/home/.claude/sessions'

const PANE_PROPS = {
  title: 'Agents',
  isFocused: true,
  bodyColumns: 100,
  placement: 'dock',
  scroll: { offset: 0, bodyRows: 40 },
  view: {},
} as const

test('the pane draws repo tabs with their marks, and a tab narrows the list', async ($, on) => {
  on('env.get', ($, e) => ({ value: e.name === 'HOME' ? '/home' : undefined }))
  on('session.id', () => ({ value: 'self' }))
  on('fs.list', ($, e) => ({
    value:
      e.path === SESSIONS_DIR
        ? Object.keys(REGISTRY).map(name => ({ name, kind: 'file' as const, size: 1, mtimeMs: 0, isLink: false }))
        : [],
  }))
  on('fs.read', ($, e) => ({ value: JSON.stringify(REGISTRY[e.path.slice(SESSIONS_DIR.length + 1)]) }))
  on('fs.exists', () => ({ value: false }))
  on('ui.open', () => ({ value: { isPlaced: true as const } }))
  on('ui.status', () => ({ value: undefined }))
  // 2.1.289's typings make this hook's `value` `undefined`, though the op
  // answers a ProcessRunResult and the engine takes this one: cast past it.
  on('process.run', ($, e) => ({
    value: {
      exitCode: e.argv[0] === 'git' ? 1 : 0,
      stdout: e.argv[0] === 'ps' ? '101 /bin/claude\n102 /bin/claude\n103 /bin/claude\n' : '',
      stderr: '',
    } as never,
  }))

  await $.command.run({
    command: 'roster',
    args: '',
    origin: { kind: 'composer' },
    presentation: { isFullscreen: true, columns: 120 },
  })
  const ui = await $.ui.mount({
    plugin: 'agent-roster',
    surface: 'terminal',
    component: 'Pane',
    requestId: 'agent-roster',
    props: PANE_PROPS,
  })

  expect((await ui.find({ key: 'tab-*all' }))?.text).toContain('All')
  expect((await ui.find({ key: 'tab-pip-skills' }))?.text).toContain('pip-skills')
  // The counts beside the tabs: All and pip-skills each hold one waiting.
  expect(await ui.findAll({ type: 'Text', text: /^\?1$/ })).toHaveLength(2)
  expect(await ui.findAll({ type: 'Text', text: /^●1$/ })).toHaveLength(2)
  // Boxes are not found by key: the sessions are found by their text.
  const session = (tmux: RegExp) => ui.find({ type: 'Text', text: tmux })
  expect(await session(/cc-b-1/)).toBeDefined()

  await ui.press({ key: 'tab-pip-skills' })

  expect(await session(/cc-a-1/)).toBeDefined()
  expect(await session(/cc-b-1/)).toBeUndefined()
  // Idle over a day: folded until shown.
  expect(await session(/cc-a-2/)).toBeUndefined()
  await ui.press({ key: 'older' })
  expect(await session(/cc-a-2/)).toBeDefined()
  // A manual refresh rescans and keeps the tab in view.
  await ui.press({ key: 'refresh' })
  expect(await session(/cc-a-1/)).toBeDefined()
  expect(await session(/cc-b-1/)).toBeUndefined()
  await ui.unmount()
})

// One stray pane on the default tmux server, no registry entries.
function strayWorld(on: On, list: () => unknown, exists = true) {
  on('env.get', ($, e) => ({ value: e.name === 'HOME' ? '/home' : undefined }))
  on('session.id', () => ({ value: 'self' }))
  on('fs.list', ($, e) => (e.path === SESSIONS_DIR ? (list() as never) : { value: [] }))
  on('fs.read', () => ({ value: '' }))
  on('fs.exists', () => ({ value: exists }))
  on('ui.open', () => ({ value: { isPlaced: true as const } }))
  on('ui.status', () => ({ value: undefined }))
  on('process.run', ($, e) => ({
    value: {
      exitCode: e.argv[0] === 'git' ? 1 : 0,
      stdout:
        e.argv[0] === 'tmux' && e.argv.includes('-a')
          ? 'cc-boot-1\t4242\t2.1.289\t/r/boot\t1791148000\n'
          : '',
      stderr: '',
    } as never,
  }))
}

async function mountPane($: Engine) {
  await $.command.run({
    command: 'roster',
    args: '',
    origin: { kind: 'composer' },
    presentation: { isFullscreen: true, columns: 120 },
  })

  return $.ui.mount({
    plugin: 'agent-roster',
    surface: 'terminal',
    component: 'Pane',
    requestId: 'agent-roster',
    props: PANE_PROPS,
  })
}

test('a session at a startup prompt can be opened but offers no kill', async ($, on) => {
  strayWorld(on, () => ({ value: [] }))
  const ui = await mountPane($)

  expect(await ui.find({ type: 'Text', text: /cc-boot-1/ })).toBeDefined()
  expect(await ui.find({ key: 'open-4242' })).toBeDefined()
  expect(await ui.find({ key: 'kill-4242' })).toBeUndefined()
  const reply = await $.command.run({
    command: 'roster',
    args: 'kill cc-boot-1',
    origin: { kind: 'composer' },
    presentation: { isFullscreen: true, columns: 120 },
  })
  expect(JSON.stringify(reply)).toContain('startup prompt')
  await ui.unmount()
})

test('a registry that exists but cannot be listed is a failed scan, not an empty roster', async ($, on) => {
  strayWorld(on, () => ({ deny: 'EACCES: permission denied' }))
  const ui = await mountPane($)

  expect(await ui.find({ type: 'Text', text: /Last scan failed.*EACCES/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /cc-boot-1/ })).toBeUndefined()
  await ui.unmount()
})

test('a registry folder not made yet is an empty registry, not a failed scan', async ($, on) => {
  strayWorld(on, () => ({ deny: 'ENOENT: no such file or directory' }), false)
  const ui = await mountPane($)

  expect(await ui.find({ type: 'Text', text: /Last scan failed/ })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /cc-boot-1/ })).toBeDefined()
  await ui.unmount()
})

test('sessions starting a few seconds apart ask the VS Code helper question once', async ($, on) => {
  strayWorld(on, () => ({ value: [] }))
  const clock = mock.clock(on, { now: 1_000_000 })
  const store = new Map<string, unknown>()
  on('store.get', ($, e) => ({ value: store.get(e.key) as never }))
  on('store.set', ($, e) => {
    store.set(e.key, e.value)
    return { value: undefined }
  })
  on('session.surfaces', () => ({ value: ['terminal'] as never }))
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  // $.ui.ask runs as an AskUserQuestion tool call: the first one stays open.
  const asks: ((label: string) => void)[] = []
  on('tool.call', async ($, e) => {
    const input = e as unknown as { tool: string; questions?: { question: string }[] }
    if (input.tool !== 'AskUserQuestion') return { result: 'ok' } as never
    const label = await new Promise<string>(res => asks.push(res))
    const answers = Object.fromEntries((input.questions ?? []).map(q => [q.question, label]))
    return { result: { questions: input.questions, answers } } as never
  })
  const START = { cwd: '/r', surface: 'terminal' as const, isInteractive: true }

  await $.session.start(START)
  await clock.advance(3000)
  expect(asks).toHaveLength(1)
  // A second session starts while that question is still open.
  await $.session.start(START)
  await clock.advance(3000)
  expect(asks).toHaveLength(1)

  asks[0]!('Not now')
  await clock.advance(0)
  expect(store.get('vscodeHelper')).toBeGreaterThan(Date.now() + 23 * 3600_000)
})

// Two accounts' registries; `unreadable` dirs exist but cannot be listed.
function accountsWorld(on: On, unreadable: string[] = [], unreadableFiles: string[] = []) {
  const dirs: Record<string, object> = {
    '/home/.claude/sessions': { '101.json': { pid: 101, sessionId: 'a', cwd: '/r/mine', tmux: 'cc-own:@0.%0', status: 'busy', updatedAt: 0 } },
    '/home/.claude-personal/sessions': { '202.json': { pid: 202, sessionId: 'b', cwd: '/r/theirs', tmux: 'cc-other:@1.%1', status: 'busy', updatedAt: 0 } },
  }
  on('env.get', ($, e) => ({
    value:
      e.name === 'HOME'
        ? '/home'
        : e.name === 'ROSTER_CONFIG_DIRS'
          ? '~/.claude-personal:~/.claude-gone:~/.claude-locked'
          : undefined,
  }))
  on('session.id', () => ({ value: 'self' }))
  on('fs.list', ($, e) => {
    if (unreadable.includes(e.path)) return { deny: 'EACCES: permission denied' }
    const reg = dirs[e.path]
    if (!reg) return { deny: 'ENOENT: no such file or directory' }
    return { value: Object.keys(reg).map(name => ({ name, kind: 'file' as const, size: 1, mtimeMs: 0, isLink: false })) }
  })
  on('fs.read', ($, e) => {
    if (unreadableFiles.includes(e.path)) return { deny: 'EACCES: permission denied' }
    const at = e.path.lastIndexOf('/')
    return { value: JSON.stringify((dirs[e.path.slice(0, at)] as Record<string, object>)?.[e.path.slice(at + 1)]) }
  })
  on('fs.exists', ($, e) => ({ value: e.path in dirs || unreadable.includes(e.path) || unreadableFiles.includes(e.path) }))
  on('ui.open', () => ({ value: { isPlaced: true as const } }))
  on('ui.status', () => ({ value: undefined }))
  on('process.run', ($, e) => ({
    value: {
      exitCode: e.argv[0] === 'git' ? 1 : 0,
      stdout: e.argv[0] === 'ps' ? '101 /bin/claude\n202 /bin/claude\n' : '',
      stderr: '',
    } as never,
  }))
}

const bridgeText = async ($: Engine) =>
  (
    (await $.command.run({
      command: 'roster',
      args: '',
      origin: { kind: 'bridge' } as never,
      presentation: { isFullscreen: false, columns: 80 },
    })) as { text: string }
  ).text.replace(/ · \d+[a-z]+/g, ' · AGE')

test('ROSTER_CONFIG_DIRS reads each dir: the own dir untagged first, the others tagged', async ($, on) => {
  accountsWorld(on)

  expect((await bridgeText($)).split('\n')).toEqual([
    '0 need you · 2 working · 0 idle',
    '',
    'WORKING',
    '• mine — cc-own · mine · AGE',
    '• theirs — cc-other · theirs · AGE · personal',
  ])
})

test('a dir that exists but cannot be listed is a warning; the other dirs still show', async ($, on) => {
  accountsWorld(on, ['/home/.claude-locked/sessions'])
  const text = await bridgeText($)

  expect(text).toContain('• mine — cc-own')
  expect(text).toContain('• theirs — cc-other')
  expect(text.split('\n').at(-1)).toMatch(/^! could not read locked: .*EACCES/)
})

test('the pane shows that warning too', async ($, on) => {
  accountsWorld(on, ['/home/.claude-locked/sessions'])
  const ui = await mountPane($)

  expect(await ui.find({ type: 'Text', text: /could not read locked.*EACCES/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /Last scan failed/ })).toBeUndefined()
  await ui.unmount()
})

test('when every dir fails a refresh, the last good rows stay under the failure banner', async ($, on) => {
  const failing: string[] = []
  accountsWorld(on, failing)
  const ui = await mountPane($)
  expect(await ui.find({ type: 'Text', text: /cc-own/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /Last scan failed/ })).toBeUndefined()

  failing.push('/home/.claude/sessions', '/home/.claude-personal/sessions', '/home/.claude-gone/sessions', '/home/.claude-locked/sessions')
  await ui.press({ key: 'refresh' })

  expect(await ui.find({ type: 'Text', text: /Last scan failed.*EACCES/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /cc-own/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /cc-other/ })).toBeDefined()
  await ui.unmount()
})

test('a session file that lists but cannot be read is a warning for its dir', async ($, on) => {
  accountsWorld(on, [], ['/home/.claude-personal/sessions/202.json'])
  const text = await bridgeText($)

  expect(text).toContain('• mine — cc-own')
  expect(text).not.toContain('cc-other')
  expect(text.split('\n').at(-1)).toMatch(/^! could not read personal: .*EACCES/)
})


// The tmux sweep: a pane with no entry in the dir this session reads.
// `extra`: `shell` adds a pane whose pid is a zsh above a Claude registered in the work account;
// `reused` adds a pane whose pid has a long-dead work-account record (the pid was reused).
function otherAccountsWorld(on: On, listed = '', extra: { shell?: boolean; reused?: boolean; nostart?: boolean } = {}) {
  const now = Date.now()
  const registries: Record<string, Record<string, object>> = {
    '/home/.claude/sessions': { '101.json': { pid: 101, sessionId: 'a', cwd: '/r/mine', tmux: 'cc-own-1:@0.%0', status: 'busy', updatedAt: 0 } },
    '/home/.claude-work/sessions': {
      '777.json': { pid: 777, sessionId: 'w', cwd: '/r/work', tmux: 'cc-work-1:@1.%1', status: 'busy', updatedAt: 0, startedAt: now - 3_600_000 },
      ...(extra.shell ? { '951.json': { pid: 951, sessionId: 'sh', cwd: '/r/shell', tmux: 'cc-shell-1:@2.%2', status: 'busy', updatedAt: 0, startedAt: now - 180_000 } } : {}),
      ...(extra.nostart ? { '870.json': { pid: 870, sessionId: 'ns', cwd: '/r/ns', tmux: 'cc-nostart:@4.%4', status: 'idle', updatedAt: 0 } } : {}),
      ...(extra.reused ? { '860.json': { pid: 860, sessionId: 'old', cwd: '/r/old', tmux: 'cc-old:@3.%3', status: 'idle', updatedAt: 0, startedAt: now - 5 * 86_400_000 } } : {}),
    },
  }
  const calls: string[][] = []
  const recent = Math.floor(now / 1000) - 60
  const panes = [
    `cc-own-1\t101\t2.1.289\t/r/mine\t${recent}`,
    `cc-work-1\t777\t2.1.289\t/r/work\t${recent}`,
    `cc-agents\t800\t2.1.289\t/r/x\t${recent}`,
    `cc-new-1\t900\t2.1.289\t/r/new\t${recent}`,
    ...(extra.shell ? [`cc-shell-1\t950\t2.1.289\t/r/shell\t${recent}`] : []),
    ...(extra.nostart ? [`cc-nostart\t870\t2.1.289\t/r/ns\t${recent}`] : []),
    ...(extra.reused ? [`cc-reused\t860\t2.1.289\t/r/reused\t${recent}`] : []),
  ].join('\n')
  const procs = [
    '  777     1  01:00:00 /v/2.1.289',
    '  800     1     10:00 /v/2.1.289 agents',
    '  900     1     02:00 /v/2.1.289',
    '  950     1     03:00 -zsh',
    '  951   950     03:00 /v/2.1.289',
    '  860     1     00:30 /v/2.1.289',
    '  870     1     00:30 /v/2.1.289',
    '',
  ].join('\n')
  on('env.get', ($, e) => ({ value: e.name === 'HOME' ? '/home' : e.name === 'ROSTER_CONFIG_DIRS' ? listed || undefined : undefined }))
  on('session.id', () => ({ value: 'self' }))
  on('fs.list', ($, e) => {
    const names = e.path === '/home' ? ['.claude', '.claude-work', '.config', 'docs'] : Object.keys(registries[e.path.replace(/\/sessions$/, '') + '/sessions'] ?? {})
    if (e.path === '/home' || registries[e.path]) {
      return { value: (e.path === '/home' ? names : Object.keys(registries[e.path]!)).map(name => ({ name, kind: 'file' as const, size: 1, mtimeMs: 0, isLink: false })) }
    }
    return { value: [] }
  })
  on('fs.read', ($, e) => {
    calls.push(['fs.read', e.path])
    const at = e.path.lastIndexOf('/')
    return { value: JSON.stringify(registries[e.path.slice(0, at)]?.[e.path.slice(at + 1)]) }
  })
  on('fs.exists', ($, e) => {
    const at = e.path.lastIndexOf('/')
    return { value: Boolean(registries[e.path.slice(0, at)]?.[e.path.slice(at + 1)]) || e.path in registries }
  })
  on('ui.open', () => ({ value: { isPlaced: true as const } }))
  on('ui.status', () => ({ value: undefined }))
  on('process.run', ($, e) => {
    calls.push([...e.argv])
    const [bin, ...rest] = e.argv
    let stdout = ''
    if (bin === 'id') stdout = '501\n'
    else if (bin === 'tmux' && rest.includes('list-panes') && rest.includes('-a')) stdout = panes
    else if (bin === 'ps' && rest[1] === 'pid=,comm=') stdout = '101 /bin/claude\n777 /bin/claude\n'
    else if (bin === 'ps' && rest.includes('pid=,ppid=,etime=,args=')) stdout = procs
    return { value: { exitCode: bin === 'git' ? 1 : 0, stdout, stderr: '' } as never }
  })
  return calls
}

test('a pane registered in another account is labelled, the agents view is labelled, only the rest is a startup prompt', async ($, on) => {
  otherAccountsWorld(on)
  const text = await bridgeText($)

  expect(text).toContain('running in another account (work) — run /roster setup to list it')
  expect(text).toMatch(/cc-agents.*agents view/)
  expect(text).toMatch(/cc-new-1.*at a startup prompt/)
  expect(text.match(/at a startup prompt/g)).toHaveLength(1)
  expect(text).toMatch(/^1 need you/)
})

test('a dir already in ROSTER_CONFIG_DIRS is an ordinary row, with no other-account label', async ($, on) => {
  otherAccountsWorld(on, '~/.claude-work')
  const text = await bridgeText($)

  expect(text).not.toContain('another account')
  expect(text).toContain('cc-work-1')
})

const PS_PROCS = ['ps', '-ax', '-o', 'pid=,ppid=,etime=,args=']

test('the sweep asks ps once, for every process (to see under shells); a registered pane is never looked up in another account', async ($, on) => {
  const calls = otherAccountsWorld(on)
  await bridgeText($)
  const reads = calls.filter(c => c[0] === 'fs.read').map(c => c[1] ?? '')

  expect(calls.filter(c => c.join(' ').includes('pid=,ppid=,etime=,args='))).toEqual([PS_PROCS])
  expect(reads.some(p => p.includes('.claude-work') && p.endsWith('/101.json'))).toBe(false) // 101 is registered here: not a candidate
  expect(reads).toContain('/home/.claude-work/sessions/777.json') // 777 is: it was looked for
})

test('a pane whose pid is a shell above Claude is labelled by the Claude under it, not left as a startup prompt', async ($, on) => {
  otherAccountsWorld(on, '', { shell: true })
  const text = await bridgeText($)

  expect(text).toMatch(/cc-shell-1.*running in another account \(work\)/)
  expect(text.match(/at a startup prompt/g)).toHaveLength(1) // only cc-new-1
})

test('a work-account record left behind by a dead session does not label an unrelated process that reused its pid', async ($, on) => {
  otherAccountsWorld(on, '', { reused: true })
  const text = await bridgeText($)

  expect(text).toMatch(/cc-reused.*at a startup prompt/)
  expect(text).not.toMatch(/cc-reused.*another account/)
})

test('no kill is offered for an other-account or agents-view pane', async ($, on) => {
  otherAccountsWorld(on)
  const ui = await mountPane($)

  expect(await ui.find({ type: 'Text', text: /running in another account \(work\)/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /agents view/ })).toBeDefined()
  expect(await ui.find({ key: 'kill-777' })).toBeUndefined()
  expect(await ui.find({ key: 'kill-800' })).toBeUndefined()
  expect(await ui.find({ key: 'kill-101' })).toBeDefined()
  for (const [target, why] of [['cc-agents', 'agents view'], ['cc-work-1', 'another account (work)']] as const) {
    const reply = await $.command.run({ command: 'roster', args: `kill ${target}`, origin: { kind: 'composer' }, presentation: { isFullscreen: true, columns: 120 } })
    expect(JSON.stringify(reply)).toContain(why)
    expect(JSON.stringify(reply)).toContain('Refused')
  }
  await ui.unmount()
})

test('a record with no startedAt cannot be told from a reused pid, so it is not tagged: a startup prompt', async ($, on) => {
  otherAccountsWorld(on, '', { nostart: true })
  const text = await bridgeText($)

  expect(text).toMatch(/cc-nostart.*at a startup prompt/)
  expect(text).not.toMatch(/cc-nostart.*another account/)
})

// --- the clickable "N waiting" button in the band above the prompt -------------------------

type DrawnNode = { type?: string; key?: string; props?: object; text?: string; children?: (DrawnNode | string)[] }
const textOf = (n: DrawnNode | string): string =>
  typeof n === 'string' ? n : (n.text ?? '') + ((n.props as { label?: string } | undefined)?.label ?? '') + (n.children ?? []).map(textOf).join('')
const BAND = (props: Record<string, unknown> = {}) =>
  ({ plugin: 'agent-roster', surface: 'terminal' as const, component: 'AbovePrompt' as const, props: { hasSurvey: false, isWorking: false, maxRows: 10, bodyColumns: 120, ...props } as never })
async function bandRows(ui: { drawn: () => Promise<unknown> }): Promise<string[]> {
  const root = (await ui.drawn()) as DrawnNode
  return (root.children ?? []).map(textOf).filter(l => l !== '')
}

// `waiting` registry entries that wait on the person, plus one that is busy.
function bandWorld(on: On, opts: { waiting: number; surfaces?: string[]; inner?: string } = { waiting: 2 }) {
  const seen = { status: [] as (string | undefined)[], opened: 0, invalidated: 0 }
  const reg: Record<string, object> = { '900.json': { pid: 900, sessionId: 'b', cwd: '/r/busy', tmux: 'cc-busy:@0.%0', status: 'busy', updatedAt: 0 } }
  for (let i = 0; i < opts.waiting; i++) {
    reg[`${100 + i}.json`] = { pid: 100 + i, sessionId: `w${i}`, cwd: `/r/w${i}`, tmux: `cc-w${i}:@0.%${i}`, status: 'waiting', updatedAt: 0 }
  }
  on('env.get', ($, e) => ({ value: e.name === 'HOME' ? '/home' : undefined }))
  on('session.id', () => ({ value: 'self' }))
  on('session.surfaces', () => ({ value: (opts.surfaces ?? ['terminal']) as never }))
  on('fs.list', ($, e) => ({ value: e.path === SESSIONS_DIR ? Object.keys(reg).map(name => ({ name, kind: 'file' as const, size: 1, mtimeMs: 0, isLink: false })) : [] }))
  on('fs.read', ($, e) => ({ value: JSON.stringify(reg[e.path.slice(SESSIONS_DIR.length + 1)]) }))
  on('fs.exists', () => ({ value: false }))
  on('ui.open', () => { seen.opened++; return { value: { isPlaced: true as const } } })
  on('ui.status', (_$, e) => { seen.status.push((e as { text?: string }).text); return { value: undefined } })
  on('ui.invalidate', () => { seen.invalidated++; return { value: undefined } })
  on('process.run', ($, e) => ({
    value: {
      exitCode: e.argv[0] === 'git' ? 1 : 0,
      stdout: e.argv[0] === 'ps' ? Object.keys(reg).map(n => `${n.replace('.json', '')} /bin/claude`).join('\n') + '\n' : '',
      stderr: '',
    } as never,
  }))
  // Whatever the mods beneath draw in the band; an empty Box when there is nothing.
  const text = opts.inner
  on('ui.render', ($, e) => { const { Box, Text } = $.ui.resolve(e); return text ? <Box><Text>{text}</Text></Box> : <Box /> })
  return { seen, reg }
}

const refreshAndMount = async ($: Engine, props: Record<string, unknown> = {}) => {
  await bridgeText($) // a scan fills the roster
  return $.ui.mount(BAND(props))
}

test('N waiting draws one button row that opens the roster pane like /roster', async ($, on) => {
  const { seen } = bandWorld(on, { waiting: 2 })
  const ui = await refreshAndMount($)

  expect(await bandRows(ui)).toEqual(['👥 2 waiting · open roster'])
  await ui.press({ key: 'roster-waiting' })
  expect(seen.opened).toBe(1)
  await ui.unmount()
})

test('nothing waiting: no row, and the engine tree is returned untouched', async ($, on) => {
  bandWorld(on, { waiting: 0, inner: 'INNER' })
  const ui = await refreshAndMount($)

  expect(await bandRows(ui)).toEqual(['INNER'])
  await ui.unmount()
})

test('what other mods draw stays first and our row follows it', async ($, on) => {
  bandWorld(on, { waiting: 1, inner: 'CENSUS LINE' })
  const ui = await refreshAndMount($)

  expect(await bandRows(ui)).toEqual(['CENSUS LINE', '👥 1 waiting · open roster'])
  await ui.unmount()
})

test('a survey holding the band is never drawn over', async ($, on) => {
  bandWorld(on, { waiting: 3, inner: 'SURVEY' })
  const ui = await refreshAndMount($, { hasSurvey: true })

  expect(await bandRows(ui)).toEqual(['SURVEY'])
  await ui.unmount()
})

test('maxRows: dropped with no room, kept with one row free', async ($, on) => {
  bandWorld(on, { waiting: 1 })
  await bridgeText($)
  const none = await $.ui.mount(BAND({ maxRows: 0 }))
  expect(await bandRows(none)).toEqual([])
  await none.unmount()
  const one = await $.ui.mount(BAND({ maxRows: 1 }))
  expect(await bandRows(one)).toEqual(['👥 1 waiting · open roster'])
  await one.unmount()
})

test('maxRows 1 with another mod already drawing leaves no room for our row', async ($, on) => {
  bandWorld(on, { waiting: 1, inner: 'CENSUS LINE' })
  const ui = await refreshAndMount($, { maxRows: 1 })

  expect(await bandRows(ui)).toEqual(['CENSUS LINE'])
  await ui.unmount()
})

test('a narrow band truncates the label to bodyColumns', async ($, on) => {
  bandWorld(on, { waiting: 12 })
  const ui = await refreshAndMount($, { bodyColumns: 12 })
  const [row] = await bandRows(ui)

  expect(row!.length).toBeLessThanOrEqual(12)
  expect(row).toMatch(/…$/)
  await ui.unmount()
})

test('the old status line is cleared, not left behind, when the band can draw', async ($, on) => {
  const { seen } = bandWorld(on, { waiting: 2 })
  await bridgeText($)

  expect(seen.status.filter(s => s !== undefined)).toEqual([])
  // the clear is a call of its own: a missing one would leave an older line on screen
  expect(seen.status.length).toBeGreaterThan(0)
  expect(seen.status.at(-1)).toBeUndefined()
})

test('the line is cleared again once the waiting sessions are gone', async ($, on) => {
  const { seen, reg } = bandWorld(on, { waiting: 1, surfaces: ['vscode'] })
  await bridgeText($)
  expect(seen.status.at(-1)).toBe('agents: 1 waiting')
  delete reg['100.json']
  await bridgeText($)
  expect(seen.status.length).toBeGreaterThan(1)
  expect(seen.status.at(-1)).toBeUndefined()
})

test('a terminal and a VS Code window attached together: the status line stays for the one without the band', async ($, on) => {
  const { seen } = bandWorld(on, { waiting: 2, surfaces: ['terminal', 'vscode'] })
  await bridgeText($)

  expect(seen.status.at(-1)).toBe('agents: 2 waiting')
})

test('terminal and desktop both draw the band: the line is cleared', async ($, on) => {
  const { seen } = bandWorld(on, { waiting: 2, surfaces: ['terminal', 'desktop'] })
  await bridgeText($)

  expect(seen.status.at(-1)).toBeUndefined()
  expect(seen.status.some(s => s !== undefined)).toBe(false)
})

test('no surface attached: the line stays rather than the notice vanishing', async ($, on) => {
  const { seen } = bandWorld(on, { waiting: 1, surfaces: [] })
  await bridgeText($)

  expect(seen.status.at(-1)).toBe('agents: 1 waiting')
})

test('a surface without the band (vscode, mobile only) keeps the plain status line', async ($, on) => {
  const { seen } = bandWorld(on, { waiting: 2, surfaces: ['vscode'] })
  await bridgeText($)

  expect(seen.status.at(-1)).toBe('agents: 2 waiting')
})

test('the band is redrawn when the waiting count changes, and only then', async ($, on) => {
  const { seen, reg } = bandWorld(on, { waiting: 1 })
  await bridgeText($)
  const after1 = seen.invalidated
  expect(after1).toBeGreaterThan(0)

  await bridgeText($) // same count again
  expect(seen.invalidated).toBe(after1)

  reg['150.json'] = { pid: 150, sessionId: 'x', cwd: '/r/x', tmux: 'cc-x:@0.%9', status: 'waiting', updatedAt: 0 }
  await bridgeText($)
  expect(seen.invalidated).toBe(after1 + 1)
})
