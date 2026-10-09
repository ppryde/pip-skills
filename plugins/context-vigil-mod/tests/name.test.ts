import { expect, test } from 'claude-code/testing'
import { transcriptPathFor } from '../plugin/core/cache-ttl'
import { watchPaths } from '../plugin/core/git'
import { COMMANDS, NAME, TOOL_FULL, classicSessionPath, configRoot, eventsPath, handoverPath } from '../plugin/core/name'

test('names', () => {
  expect(NAME).toBe('context-vigil-mod')
  expect(TOOL_FULL).toBe('mcp__context-vigil-mod__vigil_handover')
  expect(COMMANDS).toEqual({ handover: 'vigil-handover', handoverShort: 'vho', setup: 'vigil-setup', overrides: 'vigil-overrides' })
})
test('config root prefers CLAUDE_CONFIG_DIR, falls back to HOME/.claude', () => {
  expect(configRoot({ CLAUDE_CONFIG_DIR: '/cfg/', HOME: '/h' })).toBe('/cfg')
  expect(configRoot({ HOME: '/h' })).toBe('/h/.claude')
  // Neither set: no root at all, never a relative `.claude` under the session's cwd.
  expect(configRoot({})).toBe(null)
})
test('paths are per session and stay inside the mod folder', () => {
  expect(handoverPath('/cfg', 's1', 2)).toBe('/cfg/context-vigil-mod/handovers/s1-2.md')
  expect(eventsPath('/cfg', '2026-10-04', 's1')).toBe('/cfg/context-vigil-mod/events/2026-10-04/s1.jsonl')
  expect(classicSessionPath('/cfg', 's1')).toBe('/cfg/context-vigil/sessions/s1.json')
})

test('a Windows home: USERPROFILE, then HOMEDRIVE+HOMEPATH; paths keep backslashes', () => {
  expect(configRoot({ USERPROFILE: 'C:\\Users\\x' })).toBe('C:\\Users\\x\\.claude')
  expect(configRoot({ HOMEDRIVE: 'C:', HOMEPATH: '\\Users\\x' })).toBe('C:\\Users\\x\\.claude')
  expect(configRoot({ CLAUDE_CONFIG_DIR: 'D:\\cfg\\' , USERPROFILE: 'C:\\Users\\x' })).toBe('D:\\cfg')
  expect(handoverPath('C:\\Users\\x\\.claude', 's1', 2)).toBe('C:\\Users\\x\\.claude\\context-vigil-mod\\handovers\\s1-2.md')
  expect(eventsPath('C:\\c', '2026-10-04', 's1')).toBe('C:\\c\\context-vigil-mod\\events\\2026-10-04\\s1.jsonl')
  expect(transcriptPathFor('C:\\c', 'C:\\repo', 's1')).toBe('C:\\c\\projects\\C--repo\\s1.jsonl')
})

test('the git dir git prints on Windows (C:/repo/.git) is watched', () => {
  expect(watchPaths({ exitCode: 0, stdout: 'C:/repo/.git\n' } as never)).toEqual(['C:/repo/.git/HEAD', 'C:/repo/.git/index'])
})
