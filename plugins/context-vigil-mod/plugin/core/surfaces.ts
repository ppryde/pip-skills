import type { RcAnswer } from '../types'
import type { WaitReason } from './voice'

export const COUNTDOWN_MS = 30_000
export const HOLDBACK_MS = 120_000
export const RECHECK_MS = 2_000

export type GateFacts = {
  now: number
  draft: string
  onPhone: boolean
  lastBridgeAt: number | null
  rcAutoClear: RcAnswer
  latched: boolean
  countdownEndsAt: number | null
  classicActive: boolean
  unattended: boolean
}

export type Gate = { go: true } | { go: false; reason: WaitReason; recheckMs: number | null }

export function clearGate(f: GateFacts): Gate {
  if (f.classicActive) return { go: false, reason: 'classic', recheckMs: null }
  if (f.latched) return { go: false, reason: 'latched', recheckMs: null }
  if (f.draft.trim()) return { go: false, reason: 'draft', recheckMs: RECHECK_MS }
  if (f.onPhone && f.unattended) {
    // Unanswered follows the terminal (auto is on, so allowed), safeguards included: the question is asked in setup, never mid-run.
    if (f.rcAutoClear === 'no') return { go: false, reason: 'rc-declined', recheckMs: null }
    if (f.lastBridgeAt !== null && f.now - f.lastBridgeAt < HOLDBACK_MS) {
      return { go: false, reason: 'rc-holdback', recheckMs: HOLDBACK_MS - (f.now - f.lastBridgeAt) }
    }
    if (f.countdownEndsAt === null) return { go: false, reason: 'countdown-start', recheckMs: COUNTDOWN_MS }
    if (f.now < f.countdownEndsAt) return { go: false, reason: 'countdown', recheckMs: f.countdownEndsAt - f.now }
  }
  return { go: true }
}

// The one-per-session hint (never a question) when auto mode arms on the phone with no answer yet.
export function needsRcHint(onPhone: boolean, rc: RcAnswer, wouldArm: boolean): boolean {
  return onPhone && wouldArm && rc === 'unanswered'
}
