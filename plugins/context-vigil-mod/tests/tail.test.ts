import { expect, test } from 'claude-code/testing'
import { TAIL_HEADING, TAIL_MAX_BYTES, TAIL_MAX_MESSAGES, messagesAfterHandover, renderTail } from '../plugin/core/tail'
import { TOOL_FULL } from '../plugin/core/name'

const user = (text: string, extra: object = {}) => JSON.stringify({ type: 'user', message: { role: 'user', content: text }, ...extra })
const asst = (...content: object[]) => JSON.stringify({ type: 'assistant', message: { role: 'assistant', content } })
const text = (t: string) => ({ type: 'text', text: t })
const use = (name: string, input: object) => ({ type: 'tool_use', id: 'x', name, input })
const handover = asst(use(TOOL_FULL, { goal: 'G' }))
const lines = (...l: string[]) => l.join('\n') + '\n'

test('messagesAfterHandover: user prompts, assistant text and tool lines, in order, after the last handover call', () => {
  const t = lines(user('before'), handover, user('hello'), asst(text('thinking aloud'), use('Bash', { command: 'ls   -la\n/tmp' })), asst(use('Read', { file_path: '/a/b.ts' })))
  expect(messagesAfterHandover(t, TOOL_FULL)).toEqual(['User: hello', 'Assistant: thinking aloud', '→ Bash: ls -la /tmp', '→ Read: /a/b.ts'])
})

test('messagesAfterHandover: the LAST handover call wins; none found is null', () => {
  expect(messagesAfterHandover(lines(handover, user('a'), handover, user('b')), TOOL_FULL)).toEqual(['User: b'])
  expect(messagesAfterHandover(lines(user('a')), TOOL_FULL)).toBe(null)
  expect(messagesAfterHandover(lines(handover), TOOL_FULL)).toEqual([])
})

test('messagesAfterHandover: skips tool results, thinking, meta, sidechain, the mod\'s own turns and cut lines', () => {
  const result = JSON.stringify({ type: 'user', message: { role: 'user', content: [{ type: 'tool_result', content: 'BIG' }] } })
  const t = lines('{"type":"user","mess', handover, result, asst({ type: 'thinking', thinking: 'secret' }), user('meta', { isMeta: true }), user('side', { isSidechain: true }),
    user('[context-vigil-mod] Resume from the handover'), JSON.stringify({ type: 'system', content: 'sys' }), asst(use(TOOL_FULL, { goal: 'again' })), user('real'))
  expect(messagesAfterHandover(t, TOOL_FULL)).toEqual(['User: real'])
})

test('tool lines are trimmed to 120 characters', () => {
  const [l] = messagesAfterHandover(lines(handover, asst(use('Bash', { command: 'x'.repeat(500) }))), TOOL_FULL) ?? []
  expect(l).toBe(`→ Bash: ${'x'.repeat(119)}…`)
})

test('renderTail: nothing after the handover is no section', () => {
  expect(renderTail([])).toEqual({ total: 0, shown: 0, over: false, section: '' })
})

test('renderTail: up to the cap is the whole tail, no note', () => {
  const r = renderTail(['User: a', '→ Bash: ls'])
  expect(r).toMatchObject({ total: 2, shown: 2, over: false })
  expect(r.section).toBe(`${TAIL_HEADING}\n\nUser: a\n→ Bash: ls`)
})

test('renderTail: more than 20 keeps the newest 20 and says so', () => {
  const m = Array.from({ length: 25 }, (_, i) => `User: m${i}`)
  const r = renderTail(m)
  expect(r).toMatchObject({ total: 25, shown: TAIL_MAX_MESSAGES, over: true })
  expect(r.section).toContain('(5 earlier messages left out)')
  expect(r.section).toContain('User: m24')
  expect(r.section).toContain('User: m5')
  expect(r.section).not.toContain('User: m4\n')
})

test('renderTail: the byte cap keeps the newest and says earlier lines were trimmed', () => {
  const m = Array.from({ length: 10 }, (_, i) => `User: ${i}${'é'.repeat(400)}`)   // 2 bytes each
  const r = renderTail(m)
  expect(r.over).toBe(false)
  expect(r.shown).toBeLessThan(10)
  expect(r.section).toContain('(earlier lines trimmed)')
  expect(r.section).toContain('User: 9')
  expect(r.section).not.toContain('User: 0')
  expect(new TextEncoder().encode(r.section.split('\n').slice(3).join('\n')).length).toBeLessThanOrEqual(TAIL_MAX_BYTES)
})
