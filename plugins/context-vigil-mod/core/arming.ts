import type { Activity, Mode, Settings, Who } from '../types'

const HUMAN = new Set(['composer', 'bridge', 'slack-ping'])
// Presence evidence that is not attestably the person's own message: a same-user channel the engine
// cannot attest (R1-24), a message relayed by an MCP channel server, the engine's follow-up to a UI
// action (R2-06). They disarm auto mode and nothing else.
const DISARM_ONLY = new Set(['unclassified', 'channel', 'auto-continuation'])

export function classifyOrigin(kind: string): Who {
  if (HUMAN.has(kind)) return 'human'
  if (kind === 'sdk') return 'headless'
  return 'agent'
}

export const EMPTY_ACTIVITY: Activity = {
  lastHumanAt: null, lastHumanOrigin: null, lastBridgeAt: null, lastAgentAt: null, headless: false,
}

export type Signal =
  | { kind: 'prompt'; origin: string; at: number }
  | { kind: 'human-command'; at: number }
  | { kind: 'edit'; at: number }
  | { kind: 'agent-step'; at: number }

export function record(a: Activity, s: Signal): Activity {
  switch (s.kind) {
    case 'prompt': {
      // An origin the engine cannot attest might be a person: it disarms auto mode and restarts the
      // idle clock, and counts for nothing else (not a phone fact, not a return, not agent work). R1-24.
      if (DISARM_ONLY.has(s.origin)) return { ...a, lastHumanAt: s.at }
      const who = classifyOrigin(s.origin)
      if (who === 'human') {
        return { ...a, lastHumanAt: s.at, lastHumanOrigin: s.origin, lastBridgeAt: s.origin === 'bridge' ? s.at : a.lastBridgeAt }
      }
      return { ...a, lastAgentAt: s.at, headless: a.headless || who === 'headless' }
    }
    case 'human-command':
    case 'edit':
      return { ...a, lastHumanAt: s.at }
    case 'agent-step':
      return { ...a, lastAgentAt: s.at }
  }
}

export const WORKING_MS = 120_000

export function mode(a: Activity, now: number, s: Pick<Settings, 'idleMin'>): Mode {
  const engaged = !a.headless && a.lastHumanAt !== null && now - a.lastHumanAt < s.idleMin * 60_000
  if (engaged) return 'attended'
  const working = a.lastAgentAt !== null && now - a.lastAgentAt < WORKING_MS
  return working ? 'auto' : 'idle'
}

export function armed(a: Activity, now: number, s: Pick<Settings, 'idleMin' | 'auto'>): boolean {
  return s.auto && mode(a, now, s) === 'auto'
}

export function transition(prev: Mode, next: Mode): 'arm' | 'disarm' | null {
  if (next === 'auto' && prev !== 'auto') return 'arm'
  if (prev === 'auto' && next !== 'auto') return 'disarm'
  return null
}

export function onPhone(a: Activity): boolean {
  return a.lastHumanOrigin === 'bridge'
}
