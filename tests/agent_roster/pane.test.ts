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
function accountsWorld(on: On, unreadable: string[] = []) {
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
    const at = e.path.lastIndexOf('/')
    return { value: JSON.stringify((dirs[e.path.slice(0, at)] as Record<string, object>)?.[e.path.slice(at + 1)]) }
  })
  on('fs.exists', ($, e) => ({ value: e.path in dirs || unreadable.includes(e.path) }))
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

test('when every dir fails the last good roster stays with the failure banner', async ($, on) => {
  accountsWorld(on, ['/home/.claude/sessions', '/home/.claude-personal/sessions', '/home/.claude-gone/sessions', '/home/.claude-locked/sessions'])
  const ui = await mountPane($)

  expect(await ui.find({ type: 'Text', text: /Last scan failed.*EACCES/ })).toBeDefined()
  await ui.unmount()
})
