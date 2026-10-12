import { expect, test } from 'claude-code/testing'
import { archiveName, lastTitle } from '../plugin/core/title'

test('lastTitle: the last custom-title line wins; ai-title is not a name', () => {
  const t = ['{"type":"ai-title","aiTitle":"Banana"}', '{"type":"custom-title","customTitle":"A"}', '{"type":"user"}', '{"type":"custom-title","customTitle":"Archive: A"}', ''].join('\n')
  expect(lastTitle(t)).toBe('Archive: A')
  expect(lastTitle('{"type":"ai-title","aiTitle":"Banana"}\n')).toBe(null)
  expect(lastTitle('{"type":"custom-title","customTitle":')).toBe(undefined)   // a cut line: cannot tell
  expect(lastTitle('{"type":"custom-title","customTitle":"Say \\"hi\\""}')).toBe('Say "hi"')
})

test('lastTitle: a later row that only nests the text (a tool input) does not hide the real title', () => {
  const t = [
    '{"type":"custom-title","customTitle":"Real"}',
    '{"type":"assistant","message":{"content":[{"type":"tool_use","input":{"type":"custom-title","customTitle":"Fake"}}]}}',
  ].join('\n')
  expect(lastTitle(t)).toBe('Real')
  expect(lastTitle(t.split('\n')[1] ?? '')).toBe(null)
})

test('the archive prefix is never nested', () => {
  expect(archiveName('My work')).toBe('Archive: My work')
  expect(archiveName('Archive: My work')).toBe('Archive: My work')
})
