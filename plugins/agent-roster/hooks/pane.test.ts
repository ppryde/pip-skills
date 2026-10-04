import { expect, test } from 'claude-code/testing'

// The test's hooks stand for the engine beneath the mod: a fake HOME holding
// one account's session registry, `ps` reporting every pid alive, no git, no
// transcripts.
const REGISTRY: Record<string, object> = {
  '1.json': { pid: 1, sessionId: 'a', cwd: '/r/pip-skills', tmux: 'cc-a-1:@0.%0', status: 'waiting', updatedAt: 0 },
  '2.json': { pid: 2, sessionId: 'b', cwd: '/r/warehouse', tmux: 'cc-b-1:@1.%1', status: 'busy', updatedAt: 0 },
  '3.json': { pid: 3, sessionId: 'c', cwd: '/r/pip-skills', tmux: 'cc-a-2:@2.%2', status: 'idle', updatedAt: 0 },
}
const SESSIONS_DIR = '/home/.claude-personal/sessions'

const PANE_PROPS = {
  title: 'Agents',
  isFocused: true,
  bodyColumns: 100,
  placement: 'dock',
  scroll: { offset: 0, bodyRows: 40 },
  view: {},
} as const

test('the pane draws repo tabs with their marks, and a tab narrows the list', async ($, on) => {
  on('env.get', () => ({ value: '/home' }))
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
  on('process.run', ($, e) => ({
    value: {
      exitCode: e.argv[0] === 'git' ? 1 : 0,
      stdout: e.argv[0] === 'ps' ? '1\n2\n3\n' : '',
      stderr: '',
    },
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

  expect((await ui.find({ key: 'tab-*all' }))?.text).toContain('All ◆1 ●1')
  expect((await ui.find({ key: 'tab-pip-skills' }))?.text).toContain('pip-skills ◆1')
  expect((await ui.find({ key: 'tab-warehouse' }))?.text).toContain('warehouse ●1')
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
  await ui.unmount()
})
