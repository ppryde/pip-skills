import { describe, expect, test } from 'claude-code/testing'
import { transcriptPathFor, ttlFromWrites, parseWrites, TAIL_CMD, cacheLinesFromText, tailBytes } from '../plugin/core/cache-ttl'

const row = (h1: number, m5: number) => `{"ephemeral_1h_input_tokens":${h1},"ephemeral_5m_input_tokens":${m5}}`

describe('parseWrites', () => {
  test('reads the split from the last row that wrote, either key order', () => {
    const out = `"cache_creation":${row(0, 50)}\n"cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":123}\n`
    expect(parseWrites(out)).toEqual({ h1: 123, m5: 0 })
  })
  test('a trailing pure cache read does not hide the last write', () => {
    expect(parseWrites(`"cache_creation":${row(7, 0)}\n"cache_creation":${row(0, 0)}\n`)).toEqual({ h1: 7, m5: 0 })
  })
  test('no rows, or only pure reads, is null', () => {
    expect(parseWrites('')).toBe(null)
    expect(parseWrites(`"cache_creation":${row(0, 0)}\n`)).toBe(null)
    expect(parseWrites('garbage\n')).toBe(null)
  })
  test('the tail command is bounded and never reads whole rows', () => {
    expect(TAIL_CMD).toContain('tail -c 65536')
    expect(TAIL_CMD).toContain('grep -o')
  })
})

describe('ttlFromWrites', () => {
  test('1h tokens only is 1h; 5m tokens only is 5m', () => {
    expect(ttlFromWrites({ h1: 10, m5: 0 })).toBe('1h')
    expect(ttlFromWrites({ h1: 0, m5: 10 })).toBe('5m')
  })
  test('mixed tokens: 5m wins, because the shortest-lived write goes cold first', () => {
    expect(ttlFromWrites({ h1: 900, m5: 1 })).toBe('5m')
  })
  test('no write found is unknown', () => expect(ttlFromWrites(null)).toBe('unknown'))
})

test('transcriptPathFor mirrors how Claude Code names a project folder', () => {
  expect(transcriptPathFor('/cfg', '/Users/p/repos/x.y/.claude/worktrees/w', 'abc'))
    .toBe('/cfg/projects/-Users-p-repos-x-y--claude-worktrees-w/abc.jsonl')
})

test('the file fallback tails by UTF-8 bytes, as tail -c does, not by UTF-16 units', () => {
  expect(tailBytes('aé€😀', 4)).toBe('😀')
  expect(tailBytes('aé€😀', 7)).toBe('€😀')
  expect(tailBytes('abc', 10)).toBe('abc')
  const old = '"cache_creation":{"ephemeral_1h_input_tokens":9}'
  expect(cacheLinesFromText(old + '€'.repeat(30000))).toBe('')
  expect(cacheLinesFromText(old + '€'.repeat(100))).toBe(old)
})
