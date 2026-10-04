// Which prompt-cache lifetime the session's main conversation is writing — PROBES §11.
// 'unknown' is the honest start: nothing here guesses 1h, because warming a cold 5-minute
// cache is the opposite of what last light is for.
export type CacheTtl = '1h' | '5m' | 'unknown'
export type Writes = { h1: number; m5: number }

const MS: Record<'1h' | '5m', number> = { '1h': 3_600_000, '5m': 300_000 }

export function ttlMsOf(ttl: CacheTtl): number | null {
  return ttl === 'unknown' ? null : MS[ttl]
}

// Reads the usage split off the end of the transcript without ever loading a whole row: grep -o
// prints only each row's `cache_creation` object. Positional args: $1 = transcript path.
export const TAIL_CMD = 'tail -c 1000000 "$1" | grep -o \'"cache_creation":{[^}]*}\' | tail -n 50'

const field = (line: string, key: string): number => {
  const m = new RegExp(`"ephemeral_${key}_input_tokens":(\\d+)`).exec(line)
  return m ? Number.parseInt(m[1] ?? '0', 10) : 0
}

// The split of the LAST response that wrote to the cache. A pure cache read writes nothing and
// says nothing about the lifetime, so it is skipped. null = no write in the tail.
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

// Any 5m write makes it 5m: content written for five minutes goes cold first, and the cost of
// warming a cold cache is worse than the cost of skipping a warm one.
export function ttlFromWrites(w: Writes | null, prev: CacheTtl): CacheTtl {
  if (w === null) return prev
  return w.m5 > 0 ? '5m' : '1h'
}

// A model switch reports the lifetime outright; the next response confirms or overrides it.
export function ttlFromSwitch(label: unknown, prev: CacheTtl): CacheTtl {
  return label === '1h' || label === '5m' ? label : prev
}

// Where Claude Code keeps a session's transcript, for when no event has carried the path yet.
export function transcriptPathFor(configRoot: string, cwd: string, sessionId: string): string {
  return `${configRoot}/projects/${cwd.replace(/[^A-Za-z0-9]/g, '-')}/${sessionId}.jsonl`
}
