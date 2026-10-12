import { expect, test } from 'claude-code/testing'
import { archiveName, lastTitle, unarchived } from '../plugin/core/title'

test('lastTitle: the last custom-title line wins; ai-title is not a name', () => {
  const t = ['{"type":"ai-title","aiTitle":"Banana"}', '{"type":"custom-title","customTitle":"A"}', '{"type":"user"}', '{"type":"custom-title","customTitle":"Archive: A"}', ''].join('\n')
  expect(lastTitle(t)).toBe('Archive: A')
  expect(lastTitle('{"type":"ai-title","aiTitle":"Banana"}\n')).toBe(null)
  expect(lastTitle('{"type":"custom-title","customTitle":')).toBe(undefined)   // a cut line: cannot tell
  expect(lastTitle('{"type":"custom-title","customTitle":"Say \\"hi\\""}')).toBe('Say "hi"')
})

test('the archive prefix is never nested, and every one comes off for the successor', () => {
  expect(archiveName('My work')).toBe('Archive: My work')
  expect(archiveName('Archive: My work')).toBe('Archive: My work')
  expect(unarchived('Archive: My work')).toBe('My work')
  expect(unarchived('Archive: Archive: My work')).toBe('My work')
  expect(unarchived('My work')).toBe('My work')
  expect(unarchived('Archive: ')).toBe('')
})
