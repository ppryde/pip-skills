import { expect, test } from 'claude-code/testing'
import { RATES } from '../plugin/core/rates'
import { ratesFor, responseUsd, subagentDir, subagentShown, sumSubagents, transcriptUsd } from '../plugin/core/subagents'
import type { SubagentCache } from '../plugin/core/subagents'

const near = (a: number | null, b: number): boolean => a !== null && Math.abs(a - b) < 1e-9

const line = (id: string | null, model: string, usage: Record<string, unknown>, extra: Record<string, unknown> = {}) =>
  JSON.stringify({ type: 'assistant', message: { ...(id ? { id } : {}), model, usage, content: [] }, ...extra })

test('rates resolve exactly, then by the longest family prefix on a dash boundary, else not at all', () => {
  expect(ratesFor('claude-opus-5-5')).toBe(RATES['claude-opus-5-5'])
  expect(ratesFor('claude-haiku-4-5-20251001')).toBe(RATES['claude-haiku-4-5'])
  expect(ratesFor('claude-fable-5-1')).toBe(RATES['claude-fable-5-1']) // never claude-fable-5's row
  expect(ratesFor('claude-sonnet-5-5')).toBe(RATES['claude-sonnet-5'])
  expect(ratesFor('claude-opus-55')).toBeNull()
  expect(ratesFor('gpt-5')).toBeNull()
  expect(ratesFor('toString')).toBeNull()
  expect(ratesFor(null)).toBeNull()
})

test('a response is priced like chronicle: cache writes by TTL, the unsplit remainder at the 5m rate', () => {
  // claude-opus-5-5: input 4, output 20, cache read 0.2 per MTok; writes 1.25x (5m) and 2x (1h) input
  const usd = responseUsd('claude-opus-5-5', {
    input_tokens: 1_000_000, output_tokens: 1_000_000, cache_read_input_tokens: 1_000_000,
    cache_creation_input_tokens: 3_000_000, cache_creation: { ephemeral_5m_input_tokens: 1_000_000, ephemeral_1h_input_tokens: 1_000_000 },
  })
  // 4 + 20 + 0.2 + (1M 5m + 1M unsplit) * 5 + 1M * 8
  expect(near(usd, 4 + 20 + 0.2 + 10 + 8)).toBe(true)
  expect(responseUsd('mystery-model', { output_tokens: 10 })).toBeNull()
  expect(responseUsd('claude-opus-5-5', { output_tokens: -5, input_tokens: Number.NaN })).toBe(0)
})

test('a transcript counts each response once, however many content-block lines repeat its usage', () => {
  const u = { input_tokens: 0, output_tokens: 100_000 } // claude-sonnet-5: $1.00
  const text = [
    line('msg_1', 'claude-sonnet-5-5', u),
    line('msg_1', 'claude-sonnet-5-5', u),
    line('msg_2', 'claude-sonnet-5-5', u),
    JSON.stringify({ type: 'user', message: { content: 'hi' } }),
    '{"usage": not json',
    line('msg_3', 'mystery-model', u),
    '',
  ].join('\n')
  const got = transcriptUsd(text)
  expect(near(got.usd, 2)).toBe(true)
  expect(got.unpriced).toBe(1)
  expect(transcriptUsd('').usd).toBe(0)
})

test('responses with no id are each counted', () => {
  const u = { output_tokens: 100_000 }
  expect(near(transcriptUsd([line(null, 'claude-sonnet-5', u), line(null, 'claude-sonnet-5', u)].join('\n')).usd, 2)).toBe(true)
})

test('the subagents directory sits beside the transcript, in its own separator', () => {
  expect(subagentDir('/cfg/projects/-repo/s1.jsonl')).toBe('/cfg/projects/-repo/s1/subagents')
  expect(subagentDir('C:\\Users\\u\\.claude\\projects\\-repo\\s1.jsonl')).toBe('C:\\Users\\u\\.claude\\projects\\-repo\\s1\\subagents')
  expect(subagentDir('/cfg/projects/-repo/s1.txt')).toBeNull()
  expect(subagentDir(null)).toBeNull()
})

test('summing re-reads only files whose size changed, ignores other files and prunes the cache', async () => {
  const dir = '/cfg/projects/-repo/s1/subagents'
  const one = line('m1', 'claude-sonnet-5', { output_tokens: 100_000 })
  const files: Record<string, string> = { [`${dir}/agent-a.jsonl`]: one, [`${dir}/agent-b.jsonl`]: one }
  const reads: string[] = []
  const read = async (p: string) => { reads.push(p); return files[p] ?? null }
  const cache: SubagentCache = new Map()
  const entries = [
    { name: 'agent-a.jsonl', kind: 'file', size: 10 },
    { name: 'agent-a.meta.json', kind: 'file', size: 5 },
    { name: 'agent-b.jsonl', kind: 'file', size: 10 },
    { name: 'agent-c.jsonl', kind: 'dir', size: 0 },
  ]
  expect(near(await sumSubagents(dir, entries, cache, read), 2)).toBe(true)
  expect(reads).toHaveLength(2)

  reads.length = 0
  expect(near(await sumSubagents(dir, entries, cache, read), 2)).toBe(true)
  expect(reads).toHaveLength(0) // nothing grew

  files[`${dir}/agent-b.jsonl`] = [one, line('m2', 'claude-sonnet-5', { output_tokens: 100_000 })].join('\n')
  const grown = entries.map(e => (e.name === 'agent-b.jsonl' ? { ...e, size: 20 } : e))
  expect(near(await sumSubagents(dir, grown, cache, read), 3)).toBe(true)
  expect(reads).toEqual([`${dir}/agent-b.jsonl`])

  expect(near(await sumSubagents(dir, grown.filter(e => e.name !== 'agent-a.jsonl'), cache, read), 2)).toBe(true)
  expect(cache.has(`${dir}/agent-a.jsonl`)).toBe(false)
})

test('an unreadable file keeps its last figure; no subagent transcripts at all is null', async () => {
  const dir = '/d'
  const cache: SubagentCache = new Map([['/d/agent-a.jsonl', { size: 1, usd: 0.5 }]])
  expect(await sumSubagents(dir, [{ name: 'agent-a.jsonl', kind: 'file', size: 2 }], cache, async () => null)).toBe(0.5)
  expect(await sumSubagents(dir, [{ name: 'notes.txt', kind: 'file', size: 2 }], new Map(), async () => '')).toBeNull()
})

test('the drawn figure never exceeds the session total and hides at zero', () => {
  expect(subagentShown(1.2, 3)).toBe(1.2)
  expect(subagentShown(5, 3)).toBe(3)
  expect(subagentShown(1.2, null)).toBe(1.2)
  expect(subagentShown(0, 3)).toBeNull()
  expect(subagentShown(null, 3)).toBeNull()
})
