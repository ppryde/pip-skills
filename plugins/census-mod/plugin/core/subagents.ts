// What a session's subagents have cost, from their transcripts (<project>/<session>/subagents/agent-*.jsonl).
// The engine's cost is one total (subagents included) with no split, so the 🕵️ figure is priced here, at the
// list prices chronicle uses (./rates, generated from chronicle's pricing.py). A port of chronicle's
// rates_for and turn_cost; a model the table does not know is left unpriced, never guessed.
import { joinPath } from './home'
import { CACHE_WRITE_1H_MULTIPLIER, CACHE_WRITE_5M_MULTIPLIER, RATES } from './rates'
import type { Rates } from './rates'

const MTOK = 1_000_000

/** Exact id first, else the longest table key the id extends on a `-` boundary (claude-haiku-4-5-20251001 -> claude-haiku-4-5). */
export function ratesFor(model: string | null | undefined): Rates | null {
  if (!model) return null
  if (Object.prototype.hasOwnProperty.call(RATES, model)) return RATES[model] ?? null
  let best: string | null = null
  for (const key of Object.keys(RATES)) if (model.startsWith(`${key}-`) && (best === null || key.length > best.length)) best = key
  return best === null ? null : (RATES[best] ?? null)
}

export type Usage = {
  input_tokens?: number
  output_tokens?: number
  cache_read_input_tokens?: number
  cache_creation_input_tokens?: number
  cache_creation?: { ephemeral_5m_input_tokens?: number; ephemeral_1h_input_tokens?: number }
}

const n = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : 0)

/** USD for one response at list prices; null when the model is unpriced. Cache writes by TTL, any unsplit part at the 5m rate. */
export function responseUsd(model: string | null | undefined, u: Usage): number | null {
  const r = ratesFor(model)
  if (!r) return null
  const w5 = n(u.cache_creation?.ephemeral_5m_input_tokens)
  const w1 = n(u.cache_creation?.ephemeral_1h_input_tokens)
  const write5m = w5 + Math.max(0, n(u.cache_creation_input_tokens) - (w5 + w1))
  const usd =
    n(u.input_tokens) * r.input +
    n(u.cache_read_input_tokens) * r.cache_read +
    write5m * (r.cache_write_5m ?? r.input * CACHE_WRITE_5M_MULTIPLIER) +
    w1 * (r.cache_write_1h ?? r.input * CACHE_WRITE_1H_MULTIPLIER) +
    n(u.output_tokens) * r.output
  return usd / MTOK
}

/**
 * One transcript's cost. A response is written as one line per content block, all sharing message.id and the
 * same usage, so responses are keyed by id (the last line wins). Lines that do not parse are skipped.
 */
export function transcriptUsd(text: string): { usd: number; unpriced: number } {
  const byId = new Map<string, { model: unknown; usage: Usage }>()
  let anon = 0
  for (const line of text.split('\n')) {
    if (!line.includes('"usage"')) continue
    let rec: unknown
    try {
      rec = JSON.parse(line)
    } catch {
      continue
    }
    const msg = (rec as { message?: { id?: unknown; model?: unknown; usage?: unknown } } | null)?.message
    if (!msg || typeof msg.usage !== 'object' || msg.usage === null) continue
    const id = typeof msg.id === 'string' ? msg.id : `#${anon++}`
    byId.set(id, { model: msg.model, usage: msg.usage as Usage })
  }
  let usd = 0
  let unpriced = 0
  for (const { model, usage } of byId.values()) {
    const v = responseUsd(typeof model === 'string' ? model : null, usage)
    if (v === null) unpriced++
    else usd += v
  }
  return { usd, unpriced }
}

/** <project>/<session>.jsonl -> <project>/<session>/subagents; null when the path is not a .jsonl transcript. */
export function subagentDir(transcriptPath: string | null): string | null {
  if (!transcriptPath || !transcriptPath.endsWith('.jsonl')) return null
  return joinPath(transcriptPath.slice(0, -'.jsonl'.length), 'subagents')
}

export const isSubagentTranscript = (name: string): boolean => name.startsWith('agent-') && name.endsWith('.jsonl')

/** Per-file cache: a file is re-read only when its size changed. */
export type SubagentCache = Map<string, { size: number; usd: number }>

/**
 * The subagents' total from a listing: files whose size is unchanged reuse the cache, the rest go through `read`
 * (null: unreadable, skipped this round). The cache is pruned to the listing. null when no subagent transcript exists.
 */
export async function sumSubagents(
  dir: string,
  entries: readonly { name: string; kind: string; size: number }[],
  cache: SubagentCache,
  read: (path: string) => Promise<string | null>,
): Promise<number | null> {
  const seen = new Set<string>()
  let total = 0
  let any = false
  for (const e of entries) {
    if (e.kind !== 'file' || !isSubagentTranscript(e.name)) continue
    const path = joinPath(dir, e.name)
    seen.add(path)
    any = true
    const hit = cache.get(path)
    if (hit && hit.size === e.size) {
      total += hit.usd
      continue
    }
    const text = await read(path)
    if (text === null) {
      total += hit?.usd ?? 0
      continue
    }
    const { usd } = transcriptUsd(text)
    cache.set(path, { size: e.size, usd })
    total += usd
  }
  for (const key of [...cache.keys()]) if (!seen.has(key)) cache.delete(key)
  return any ? total : null
}

/** The figure to draw: never more than the session's own total (the list-price estimate can overshoot it), null when nothing ran. */
export function subagentShown(subUsd: number | null, totalUsd: number | null): number | null {
  if (subUsd === null || subUsd <= 0) return null
  return totalUsd === null ? subUsd : Math.min(subUsd, totalUsd)
}
