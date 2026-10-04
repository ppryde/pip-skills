import { expect, test } from 'claude-code/testing'
import { appendLine, dayKey, makeRecord } from '../core/eventlog'

test('dayKey is the UTC date', () => {
  expect(dayKey(Date.UTC(2026, 9, 4, 23, 59))).toBe('2026-10-04')
  expect(dayKey(Date.UTC(2026, 0, 2, 0, 0))).toBe('2026-01-02')
})
test('a record carries ts, session, kind and the deciding facts', () => {
  const r = makeRecord(Date.UTC(2026, 9, 4, 12), 's1', 'arm', { idleMs: 1800000, origin: 'composer' })
  expect(r).toEqual({ ts: '2026-10-04T12:00:00.000Z', session: 's1', kind: 'arm', idleMs: 1800000, origin: 'composer' })
})
test('fields never overwrite ts, session or kind', () => {
  const r = makeRecord(0, 's1', 'clear', { kind: 'bogus', session: 'x', ts: 'y' })
  expect(r.kind).toBe('clear')
  expect(r.session).toBe('s1')
  expect(r.ts).toBe('1970-01-01T00:00:00.000Z')
})
test('appendLine adds exactly one JSON line', () => {
  const a = appendLine('', makeRecord(0, 's1', 'arm', {}))
  const b = appendLine(a, makeRecord(1, 's1', 'disarm', {}))
  const lines = b.trimEnd().split('\n')
  expect(lines.length).toBe(2)
  expect(JSON.parse(lines[1] ?? '').kind).toBe('disarm')
  expect(b.endsWith('\n')).toBe(true)
})
test('appendLine repairs a file missing its final newline', () => {
  expect(appendLine('{"a":1}', makeRecord(0, 's', 'arm', {})).split('\n').length).toBe(3)
})
