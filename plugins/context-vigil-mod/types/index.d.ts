export type Window = 'seven_day' | 'spend_limit'
export type RcAnswer = 'unanswered' | 'yes' | 'no'

export type Settings = {
  nudgeAt: number
  step: number
  bar: boolean
  auto: boolean
  idleMin: number
  lastLight: boolean
  lastLightAt: number
  limits: boolean
  limitPct: number
  limitWindows: Window[]
  rcAutoClear: RcAnswer
}

export type Who = 'human' | 'agent' | 'headless'
export type Mode = 'attended' | 'auto' | 'idle'

export type Activity = {
  lastHumanAt: number | null
  lastHumanOrigin: string | null
  lastBridgeAt: number | null
  lastAgentAt: number | null
  headless: boolean
}

export type Fields = {
  goal: string
  state: string
  decisions: string
  next_step: string
  open_questions: string
  failed_attempts: string
  session_name: string
}

export type Snapshot = {
  session: string
  at: string
  cwd: string
  branch: string | null
  dirty: string[]
  edited: string[]
  contextPct: number | null
}

export type Git = { branch: string | null; dirty: string[] }

export type RateLimit = { kind: string; percentUsed: number; resetsAt?: string }
export type Latch = { kind: string; resetsAtMs: number } | null

// What a reload must not forget about the person's surface (the RC gate reads them).
export type PhoneFacts = Pick<Activity, 'lastHumanOrigin' | 'lastBridgeAt'>

export type PendingReason = 'threshold' | 'request' | 'last_light' | 'limit'
export type Pending = {
  session: string
  path: string
  name: string
  reason: PendingReason
  markdown: string
  resume: boolean
  followUp: string | null
  createdAt: number
}

// A handover the model has been asked to write and has not written yet. `started` turns
// true when the instruction prompt itself passes prompt.submit, so only ITS turn's
// turn.complete counts as a missed attempt.
export type Awaiting = { reason: PendingReason; resume: boolean; attempts: number; started: boolean }

export type StepId =
  | 'nudge' | 'bar' | 'auto' | 'idle' | 'last_light' | 'last_light_at'
  | 'limits' | 'limit_pct' | 'limit_windows' | 'rc'

export type EventKind =
  | 'arm' | 'disarm' | 'threshold' | 'bar' | 'handover.requested' | 'handover.written'
  | 'guard.wait' | 'guard.baseline' | 'clear.skipped' | 'clear' | 'resume' | 'last_light.fired' | 'last_light.choice'
  | 'limit.latched' | 'limit.cleared' | 'limit.early_stop' | 'rc.answer' | 'setup'
  | 'standdown' | 'rename' | 'cache.ttl' | 'last_light.skip'

export type EventRecord = { ts: string; session: string; kind: EventKind } & Record<string, unknown>

declare module 'claude-code' {
  interface PluginState {
    // Per session, wiped by every /clear (PROBES §9). The latch and fired early stops live in
    // $.store; activity, lastLightArmed and standDown in module variables.
    'context-vigil-mod': {
      mode: Mode
      contextPct: number | null
      lastNudged: number | null
      baselinePct: number | null
      barShown: boolean
      barDismissed: boolean
      pending: Pending | null
      awaiting: Awaiting | null
      deferred: Awaiting | null
      handoverCount: number
      cacheTtl: '1h' | '5m' | 'unknown'
      transcriptPath: string | null
      countdownEndsAt: number | null
      lastApiAt: number | null
      rcAsked: boolean
      phoneFacts: PhoneFacts | null
    }
  }
}
