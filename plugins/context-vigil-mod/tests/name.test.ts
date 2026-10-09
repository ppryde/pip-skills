import { expect, test } from 'claude-code/testing'
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
