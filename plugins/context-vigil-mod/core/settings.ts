import type { Settings, Window } from '../types'

export const STORE_KEY = 'settings'

// Per session: a second session on the account must never see or wipe this one's handover.
export function pendingKey(session: string): string {
  return `pending:${session}`
}

export const DEFAULTS: Settings = {
  nudgeAt: 35, step: 5, bar: true, auto: false, idleMin: 30,
  lastLight: false, lastLightAt: 25, limits: true, limitPct: 95,
  limitWindows: ['seven_day', 'spend_limit'], rcAutoClear: 'unanswered',
}

const isPct = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && v >= 1 && v <= 100
const inRange = (v: unknown, lo: number, hi: number): v is number =>
  typeof v === 'number' && Number.isFinite(v) && v >= lo && v <= hi

export function loadSettings(raw: unknown): Settings {
  const s: Settings = { ...DEFAULTS, limitWindows: [...DEFAULTS.limitWindows] }
  if (!raw || typeof raw !== 'object') return s
  const r = raw as Record<string, unknown>
  if (isPct(r.nudgeAt)) s.nudgeAt = r.nudgeAt
  if (inRange(r.step, 1, 50)) s.step = r.step
  if (typeof r.bar === 'boolean') s.bar = r.bar
  if (typeof r.auto === 'boolean') s.auto = r.auto
  if (inRange(r.idleMin, 1, 1440)) s.idleMin = r.idleMin
  if (typeof r.lastLight === 'boolean') s.lastLight = r.lastLight
  if (isPct(r.lastLightAt)) s.lastLightAt = r.lastLightAt
  if (typeof r.limits === 'boolean') s.limits = r.limits
  if (isPct(r.limitPct)) s.limitPct = r.limitPct
  if (Array.isArray(r.limitWindows)) {
    const ok = r.limitWindows.filter((w): w is Window => w === 'seven_day' || w === 'spend_limit')
    s.limitWindows = [...new Set(ok)]
  }
  if (r.rcAutoClear === 'yes' || r.rcAutoClear === 'no' || r.rcAutoClear === 'unanswered') s.rcAutoClear = r.rcAutoClear
  return s
}
