import type { Latch, RateLimit, Settings } from '../types'

const resetMs = (l: RateLimit): number | null => {
  if (!l.resetsAt) return null
  const ms = Date.parse(l.resetsAt)
  return Number.isFinite(ms) ? ms : null
}

export function latchFromStopFailure(error: string, limits: RateLimit[], now: number): Latch {
  if (error !== 'rate_limit') return null
  // Equally full windows: the later reset, or latchCleared lifts it while the other is still full.
  const known = limits
    .filter(l => resetMs(l) !== null)
    .sort((a, b) => b.percentUsed - a.percentUsed || (resetMs(b) as number) - (resetMs(a) as number))
  const top = known[0]
  if (!top) return { kind: 'unknown', resetsAtMs: now + UNKNOWN_LATCH_MS }
  return { kind: top.kind, resetsAtMs: resetMs(top) as number }
}

const UNKNOWN_LATCH_MS = 3_600_000

export function latchFromMeasure(limits: RateLimit[], now: number): Latch {
  const full = limits.filter(l => l.percentUsed >= 100)
  const timed = full.filter(l => resetMs(l) !== null)
  // A full window with no reset time still latches, as a stop failure without one does.
  if (!timed.length) return full.length ? { kind: 'unknown', resetsAtMs: now + UNKNOWN_LATCH_MS } : null
  const last = timed.reduce((a, b) => ((resetMs(a) as number) >= (resetMs(b) as number) ? a : b))
  return { kind: last.kind, resetsAtMs: resetMs(last) as number }
}

export function latchCleared(l: Latch, now: number, limits: RateLimit[]): boolean {
  if (!l) return false
  if (now >= l.resetsAtMs) return true
  const same = limits.find(x => x.kind === l.kind)
  return same !== undefined && same.percentUsed < 100
}

export function earlyStopDue(
  limits: RateLimit[], s: Pick<Settings, 'limits' | 'limitPct' | 'limitWindows'>, fired: string[],
): { kind: string; key: string; pct: number; resetsAtMs: number } | null {
  if (!s.limits) return null
  for (const l of limits) {
    if (!(s.limitWindows as string[]).includes(l.kind)) continue
    if (l.percentUsed < s.limitPct) continue
    const ms = resetMs(l)
    if (ms === null || !l.resetsAt) continue
    const key = `${l.kind}:${l.resetsAt}`
    if (fired.includes(key)) continue
    return { kind: l.kind, key, pct: l.percentUsed, resetsAtMs: ms }
  }
  return null
}

export const RESUME_DELAY_MS = 300_000
export const HOP_MS = 3_600_000

export function nextHop(now: number, resumeAt: number): number {
  return Math.max(0, Math.min(HOP_MS, resumeAt - now))
}

export function formatHHMM(ms: number): string {
  const d = new Date(ms)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
