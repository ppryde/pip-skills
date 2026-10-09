// Shapes shared by the core modules. Nothing here touches `$`.

/** One of `$.session.usage().rateLimits`: ISO `resetsAt`, decimal `percentUsed`. */
export type RateLimit = { kind: string; percentUsed: number; resetsAt?: string }

export type Ttl = '5m' | '1h'

/** Per-session prompt-cache figures, kept in `$.store` so a reload or restart keeps them. */
export type Counters = {
  /** Main-thread turns that reported usage. Census reads it as `prompt_cache.requests`. */
  requests: number
  /** Summed TurnUsage: uncached input, cache reads, cache writes, output tokens. */
  input: number
  read: number
  create: number
  output: number
  /** `$.clock.now()` of the last counted turn; null before the first. */
  lastTurnAt: number | null
  ttl: Ttl | null
  /** Cache hit ratio of the last counted turn alone. */
  lastRatio: number | null
  /** A compaction cold-starts the prefix: not warm until the next counted turn. */
  cold: boolean
  updatedAt: number
}

export type GitState = {
  branch: string | null
  detached: boolean
  uncommitted: number
  ahead: number
  hasUpstream: boolean
}

export type Pr = { number: number; url: string; reviewState?: string }

export type Proc = { pid: number; procStart: string; version?: string }

/** Everything the payload and the band are drawn from. */
export type Snap = {
  sessionId: string
  transcriptPath: string | null
  cwd: string
  /** `git rev-parse --show-toplevel` when the session sits in a linked worktree. */
  worktreePath: string | null
  version: string | null
  model: { id: string; display_name: string } | null
  sessionName: string | null
  ctxPct: number | null
  ctxWindow: number | null
  costUsd: number | null
  /** `$.session.usage().startedAt`, ms. */
  startedAt: number | null
  rateLimits: RateLimit[]
  counters: Counters
  ttl: Ttl
  git: GitState | null
  pr: Pr | null
  proc: Proc | null
}
