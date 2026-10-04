import type { Mode } from '../types'
import { classifyOrigin } from './arming'

export const LEAD_MS = 300_000
export const TTL_1H = 3_600_000
export const TTL_5M = 300_000

export function ttlFromLabel(label: string): number {
  return label === '5m' ? TTL_5M : TTL_1H
}

export function fireAt(lastApiAt: number, ttlMs: number): number | null {
  if (ttlMs < TTL_1H) return null
  return lastApiAt + ttlMs - LEAD_MS
}

export type FireFacts = {
  enabled: boolean
  mode: Mode
  contextPct: number | null
  threshold: number
  pending: boolean
  latched: boolean
  armed: boolean
}

export function shouldFire(f: FireFacts):
  { fire: true } | { fire: false; reason: 'off' | 'not-idle' | 'small' | 'pending' | 'latched' | 'disarmed' } {
  if (!f.enabled) return { fire: false, reason: 'off' }
  if (f.mode !== 'idle') return { fire: false, reason: 'not-idle' }
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
