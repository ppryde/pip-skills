import type { Counters, Ttl } from './types'

// The prompt-cache lifetime the session's main conversation writes. Read once per turn off the
// transcript tail; ported from context-vigil-mod's core/cache-ttl.ts (same TAIL_CMD, same rule:
// any 5m write makes it 5m). Unknown is treated as 5m, the shorter and so the safer claim.
export type Writes = { h1: number; m5: number }
export const TAIL_CMD = 'tail -c 65536 "$1" | grep -o \'"cache_creation":{[^}]*}\''
export const DEFAULT_TTL: Ttl = '5m'

const field = (line: string, key: string): number => {
  const m = new RegExp(`"ephemeral_${key}_input_tokens":(\\d+)`).exec(line)
  return m ? Number.parseInt(m[1] ?? '0', 10) : 0
}

export function parseWrites(stdout: string): Writes | null {
  const lines = stdout.split('\n')
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i] ?? ''
    if (!line.includes('"cache_creation"')) continue
    const w = { h1: field(line, '1h'), m5: field(line, '5m') }
    if (w.h1 > 0 || w.m5 > 0) return w
  }
  return null
}

/** null = nothing found in the tail. */
export function ttlFromWrites(w: Writes | null): Ttl | null {
  if (w === null) return null
  return w.m5 > 0 ? '5m' : '1h'
}

export const ttlMs = (ttl: Ttl): number => (ttl === '1h' ? 3_600_000 : 300_000)

export const EMPTY_COUNTERS: Counters = {
  requests: 0, input: 0, read: 0, create: 0, output: 0,
  lastTurnAt: null, ttl: null, lastRatio: null, cold: false, updatedAt: 0,
}

export type TurnTokens = {
  input_tokens: number
  output_tokens: number
  cache_read_input_tokens: number
  cache_creation_input_tokens: number
}

/** read / (read + creation + uncached input); null when the turn read no input at all. */
export function ratio(read: number, create: number, input: number): number | null {
  const total = read + create + input
  return total > 0 ? read / total : null
}

/**
 * Fold one main-thread turn in. `TurnUsage` is the turn's real requests SUMMED (typings), so a
 * turn that ran several tool steps reports one ratio over all of them, and `requests` counts
 * turns, not API calls.
 */
export function addTurn(c: Counters, u: TurnTokens, now: number): Counters {
  return {
    requests: c.requests + 1,
    input: c.input + u.input_tokens,
    read: c.read + u.cache_read_input_tokens,
    create: c.create + u.cache_creation_input_tokens,
    output: c.output + u.output_tokens,
    lastTurnAt: now,
    ttl: c.ttl,
    lastRatio: ratio(u.cache_read_input_tokens, u.cache_creation_input_tokens, u.input_tokens),
    cold: false,
    updatedAt: now,
  }
}

export const sessionRatio = (c: Counters): number | null => ratio(c.read, c.create, c.input)
export const totalInputTokens = (c: Counters): number => c.input + c.read + c.create

/** Epoch ms the cache goes cold, or null before any counted turn. */
export function expiresAtMs(c: Counters, ttl: Ttl): number | null {
  return c.lastTurnAt === null ? null : c.lastTurnAt + ttlMs(ttl)
}

export function isWarm(c: Counters, ttl: Ttl, now: number): boolean {
  const at = expiresAtMs(c, ttl)
  return !c.cold && at !== null && now < at
}

/** A compaction rewrites the prefix: the next request writes the cache afresh. */
export const compacted = (c: Counters, now: number): Counters => ({ ...c, cold: true, updatedAt: now })

export const withTtl = (c: Counters, ttl: Ttl): Counters => ({ ...c, ttl })

export const STORE_PREFIX = 'counters:'
export const counterKey = (sessionId: string): string => `${STORE_PREFIX}${sessionId}`
export const COUNTER_KEEP_MS = 7 * 24 * 3_600_000
