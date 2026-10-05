import { classifyOrigin } from './arming'

export const LEAD_MS = 300_000
export const TTL_1H = 3_600_000

// Scheduled on the assumption of a 1-hour cache; the fire checks the assumption (PROBES §11).
export function fireAt(lastApiAt: number): number {
  return lastApiAt + TTL_1H - LEAD_MS
}

export type FireFacts = {
  enabled: boolean
  youIdle: boolean     // nothing from the person since the agent's last API activity
  agentIdle: boolean   // no step in the last WORKING_MS
  contextPct: number | null
  threshold: number
  pending: boolean
  latched: boolean
  armed: boolean
}

export function shouldFire(f: FireFacts):
  { fire: true } | { fire: false; reason: 'off' | 'not-idle' | 'small' | 'pending' | 'latched' | 'disarmed' } {
  if (!f.enabled) return { fire: false, reason: 'off' }
  if (!f.youIdle || !f.agentIdle) return { fire: false, reason: 'not-idle' }
  if (f.contextPct === null || f.contextPct < f.threshold) return { fire: false, reason: 'small' }
  if (f.pending) return { fire: false, reason: 'pending' }
  if (f.latched) return { fire: false, reason: 'latched' }
  if (!f.armed) return { fire: false, reason: 'disarmed' }
  return { fire: true }
}

export function rearm(prev: boolean, origin: string): boolean {
  return classifyOrigin(origin) === 'human' ? true : prev
}

export function holdOnReturn(f: { pendingIsLastLight: boolean; origin: string; now: number; cacheExpiresAt: number | null }): boolean {
  return f.pendingIsLastLight && classifyOrigin(f.origin) === 'human' && f.cacheExpiresAt !== null && f.now >= f.cacheExpiresAt
}
