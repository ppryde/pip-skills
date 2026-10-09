// Which prompt-cache lifetime the session's main conversation is writing — PROBES §11.
// Asked once, when last light is about to act. 'unknown' (nothing found) never fires: warming
// a cold 5-minute cache is the opposite of what last light is for.
import { joinPath } from './home'

export type CacheTtl = '1h' | '5m' | 'unknown'
export type Writes = { h1: number; m5: number }

// Reads the usage split off the end of the transcript without ever loading a whole row: grep -o
// prints only each row's `cache_creation` object. Positional args: $1 = transcript path.
export const TAIL_CMD = 'tail -c 65536 "$1" | grep -o \'"cache_creation":{[^}]*}\''

/** The last `bytes` UTF-8 bytes of the text (as `tail -c` takes them), not the last UTF-16 units: a cut mid-character is dropped. */
export function tailBytes(text: string, bytes: number): string {
  let used = 0
  let i = text.length
  while (i > 0) {
    const code = text.charCodeAt(i - 1)
    const isLow = code >= 0xdc00 && code <= 0xdfff && i > 1
    const size = isLow ? 4 : code < 0x80 ? 1 : code < 0x800 ? 2 : 3
    if (used + size > bytes) break
    used += size
    i -= isLow ? 2 : 1
  }

  return text.slice(i)
}

/** What TAIL_CMD prints, from the file's text: for where there is no sh/tail/grep (Windows). */
export function cacheLinesFromText(text: string, bytes = 65536): string {
  return (tailBytes(text, bytes).match(/"cache_creation":\{[^}]*\}/g) ?? []).join('\n')
}

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
// warming a cold cache is worse than the cost of skipping a warm one. No write found: unknown.
export function ttlFromWrites(w: Writes | null): CacheTtl {
  if (w === null) return 'unknown'
  return w.m5 > 0 ? '5m' : '1h'
}

// Where Claude Code keeps a session's transcript, for when no event has carried the path yet.
export function transcriptPathFor(configRoot: string, cwd: string, sessionId: string): string {
  return joinPath(configRoot, 'projects', cwd.replace(/[^A-Za-z0-9]/g, '-'), `${sessionId}.jsonl`)
}
