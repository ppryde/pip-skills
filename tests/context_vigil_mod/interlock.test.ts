import { expect, test } from 'claude-code/testing'
import { classicHooksInstalled } from '../../plugins/context-vigil-mod/core/interlock'

const settings = (cmd: string) => JSON.stringify({ hooks: { Stop: [{ hooks: [{ type: 'command', command: cmd }] }] } })
// The same fixture string is used by tests/context_vigil_mod/test_install.py (Task 16).
const CLASSIC_CMD = '"/s/context-vigil/scripts/context-vigil" hook stop'

test('classic hook commands are detected', () => {
  expect(classicHooksInstalled(settings(CLASSIC_CMD))).toBe(true)
  expect(classicHooksInstalled(settings('"/u/skills/context-vigil/scripts/context-vigil" hook user-prompt-submit'))).toBe(true)
})
test('other hooks, our own name, no file and junk are not classic', () => {
  expect(classicHooksInstalled(settings('python3 ~/.claude-personal/census/five-hour-guard.py'))).toBe(false)
  expect(classicHooksInstalled(settings('"/x/plugins/context-vigil-mod/scripts/context-vigil-mod" hook stop'))).toBe(false)
  expect(classicHooksInstalled(null)).toBe(false)
  expect(classicHooksInstalled('{not json')).toBe(false)
  expect(classicHooksInstalled(JSON.stringify({ hooks: 'odd' }))).toBe(false)
})
