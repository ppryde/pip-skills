// What happened in the old session after its handover was written: read from the transcript so the
// resume can carry it instead of losing it. Pure: the hook reads the file and calls this.
export const TAIL_MAX_MESSAGES = 20
export const TAIL_MAX_BYTES = 6144
const TEXT_MAX = 1500
const TOOL_SUMMARY_MAX = 120
export const TAIL_HEADING = '## Since this handover was written'
const OWN_PREFIX = '[context-vigil-mod]'

type Block = { type?: string; text?: string; name?: string; input?: unknown }
type Entry = { type?: string; isMeta?: boolean; isSidechain?: boolean; message?: { content?: string | Block[] } }

function oneLine(s: string, max: number): string {
  const t = s.replace(/\s+/g, ' ').trim()
  return t.length > max ? `${t.slice(0, max - 1)}…` : t
}

function inputSummary(input: unknown): string {
  if (input && typeof input === 'object') {
    const o = input as Record<string, unknown>
    for (const k of ['command', 'file_path', 'path', 'pattern', 'url', 'query', 'description', 'prompt']) {
      if (typeof o[k] === 'string' && o[k]) return oneLine(o[k] as string, TOOL_SUMMARY_MAX)
    }
  }
  try { return oneLine(JSON.stringify(input) ?? '', TOOL_SUMMARY_MAX) } catch { return '' }
}

function messagesOf(e: Entry, tool: string): { handover: boolean; lines: string[] } {
  const content = e.message?.content
  const lines: string[] = []
  let handover = false
  if (e.type === 'user') {
    if (e.isMeta) return { handover, lines }
    const texts = typeof content === 'string' ? [content] : (content ?? []).filter(b => b.type === 'text').map(b => b.text ?? '')
    for (const t of texts) if (t.trim() && !t.startsWith(OWN_PREFIX)) lines.push(`User: ${oneLine(t, TEXT_MAX)}`)
  } else if (e.type === 'assistant' && Array.isArray(content)) {
    for (const b of content) {
      if (b.type === 'text' && b.text?.trim()) lines.push(`Assistant: ${oneLine(b.text, TEXT_MAX)}`)
      else if (b.type === 'tool_use' && b.name === tool) handover = true
      else if (b.type === 'tool_use') lines.push(`→ ${b.name}: ${inputSummary(b.input)}`)
    }
  }
  return { handover, lines }
}

// The messages after the LAST call of `tool`, oldest first; null when the text holds no such call.
// Lines that do not parse (a chunk cut mid-line) are skipped.
export function messagesAfterHandover(transcript: string, tool: string): string[] | null {
  let after: string[] | null = null
  for (const raw of transcript.split('\n')) {
    if (!raw.trim()) continue
    let e: Entry
    try { e = JSON.parse(raw) as Entry } catch { continue }
    if (e.isSidechain) continue
    const m = messagesOf(e, tool)
    if (m.handover) after = []
    else if (after) after.push(...m.lines)
  }
  return after
}

export type Tail = { total: number; shown: number; over: boolean; section: string }

// The section to append: the newest messages within the count and byte caps, with a note when older ones were left out.
export function renderTail(messages: string[]): Tail {
  const total = messages.length
  if (total === 0) return { total, shown: 0, over: false, section: '' }
  let kept = messages.slice(-TAIL_MAX_MESSAGES)
  let bytes = 0
  const fit: string[] = []
  for (let i = kept.length - 1; i >= 0; i--) {
    bytes += new TextEncoder().encode(kept[i] + '\n').length
    if (bytes > TAIL_MAX_BYTES && fit.length > 0) break
    fit.unshift(kept[i] as string)
  }
  kept = fit
  const over = total > TAIL_MAX_MESSAGES
  const note = kept.length < total ? (over ? `(${total - kept.length} earlier messages left out)` : '(earlier lines trimmed)') : ''
  return { total, shown: kept.length, over, section: `${TAIL_HEADING}\n\n${note ? `${note}\n` : ''}${kept.join('\n')}` }
}
